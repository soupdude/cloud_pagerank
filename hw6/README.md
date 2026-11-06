# CS528 HW6: 3NF schema and two models

HW6 builds on the HW5 database (Cloud SQL instance `hw5-db`, database `hw5`), which holds the ~100,000 requests from the HW5 load test.

- **3NF schema:** `schema_3nf.sql` creates a new database, `hw6`, and copies the HW5 data into it. `migrate_schema.py` runs that file and checks the result.
- **Models:** `models.py` reads `hw6`, trains two models, and writes their test-set predictions to the bucket.
- **One-command run:** `run_hw6.sh` starts the database, migrates, creates a VM that runs the models, waits, then stops the database, deletes the VM and prints the output from the bucket.

## How to run

Prerequisites: `gcloud` logged in as the project owner, `python3` with `venv`, and HW5's Cloud SQL instance populated by the load test.

```bash
cd hw6
chmod +x *.sh
./run_hw6.sh
```

This takes about 10–15 minutes: a couple to start the database, seconds to migrate, and 5–10 for the VM to install libraries and train. When it finishes, the database is stopped, the VM is deleted, and the terminal shows the output files.

**Don't run it while the HW5 load test is still going.** It stops the database at the end, and it would also migrate a partial dataset.

Output location: `gs://cs528-12kfiles-bucket-thomas/hw6-output/`

| File | Contents |
|---|---|
| `model1_country_test_predictions.csv` | Model 1's test set: IP, actual country, predicted country, correct |
| `model2_income_test_predictions.csv` | Model 2's test set: features, actual income, predicted income, correct |
| `summary.txt` | Accuracies, baselines and model selection |
| `run.log` | The VM's full log |

Run the parts separately:

```bash
.venv/bin/python migrate_schema.py          # just the migration (database must be running)
.venv/bin/python models.py --local          # train on your laptop, write to ./output
```

## Part 2: third normal form

The HW5 `requests` table was **not** in 3NF. Its key is `id`, but two of its columns depend on another non-key column instead of on the key:

- `client_ip → country`. An IP always comes from the same country, while a country has many IPs.
- `country → is_banned`. Whether a request is banned depends only on its country.

So `id → client_ip → country → is_banned` is a chain of transitive dependencies. In practice, every request repeated its country name and banned flag. Nothing stopped two rows from recording different countries for the same IP. Changing a country's banned status meant updating thousands of rows.

The new schema moves each fact into a table whose key determines it:

```
countries   (country_id PK, name UNIQUE, is_banned)
client_ips  (client_ip PK, country_id FK -> countries)
requests    (request_id PK, client_ip FK -> client_ips, gender, age, income,
             time_of_day, requested_file, status_code)
failed_requests (id PK, request_time, requested_file, error_code)
```

- **1NF:** every value is atomic.
- **2NF:** every key is a single column, so no column can depend on part of a key.
- **3NF:** every non-key column depends only on its table's key.
  - A country's banned flag is stored once, in `countries`.
  - An IP's country is stored once, in `client_ips`.
  - A request stores only facts about that request.
- `failed_requests` was already in 3NF. Each column describes the one failed request identified by `id`. It is copied unchanged.
- `gender`, `age` and `income` stay in `requests`. The assignment gives no dependency for them. The client reports them per request, and they don't follow from the IP the way the country does.

### Transfer queries

These are in `schema_3nf.sql`, after the `CREATE TABLE` statements:

```sql
-- 1. One row per country, with its banned flag.
INSERT INTO hw6.countries (name, is_banned)
SELECT country, MAX(is_banned)
FROM hw5.requests
WHERE country IS NOT NULL
GROUP BY country;

-- 2. One row per client IP, pointing at its country.
INSERT INTO hw6.client_ips (client_ip, country_id)
SELECT ip.client_ip, c.country_id
FROM (SELECT client_ip, MIN(country) AS country
      FROM hw5.requests
      WHERE client_ip IS NOT NULL
      GROUP BY client_ip) AS ip
LEFT JOIN hw6.countries AS c ON c.name = ip.country;

-- 3. The requests, without the columns that now live in the tables above.
INSERT INTO hw6.requests (request_id, client_ip, gender, age, income, time_of_day,
                          requested_file, status_code)
SELECT id, client_ip, gender, age, income, time_of_day, requested_file, status_code
FROM hw5.requests;

-- 4. Failed requests are copied as they are.
INSERT INTO hw6.failed_requests (id, request_time, requested_file, error_code)
SELECT id, request_time, requested_file, error_code
FROM hw5.failed_requests;
```

`MIN(country)` and `MAX(is_banned)` only pick the single value that each group has. `migrate_schema.py` first confirms the dependencies hold in the data:
- No IP appears with two countries.
- No country is both banned and not banned.

After copying, it checks the result:
- Row counts match between the old and new tables.
- Joining the new tables reproduces every request's original country and banned flag.

The original row is rebuilt with:

```sql
SELECT r.*, c.name AS country, c.is_banned
FROM hw6.requests r
JOIN hw6.client_ips i ON i.client_ip = r.client_ip
LEFT JOIN hw6.countries c ON c.country_id = i.country_id;
```

## Part 3: the models

`models.py` loads every request by joining the three tables (the query above). Requests without client headers, such as curl tests, are dropped.

### The duplicate-row problem
HW5 ran both clients with the same seed, so every request appears twice, identically. A careless random split puts one copy in training and the other in the test set. A model that just memorizes rows then looks far better than it is. The models handle this as follows.

### Model 1: client IP → country (target 99%)

- **Feature:** the IP converted to a 32-bit integer. For example, `167.69.130.210` becomes `2806350546`.
- **Model:** a decision tree (scikit-learn `DecisionTreeClassifier`, fully grown).
  - On a single numeric feature, every split is a threshold on the IP number, so every leaf is a contiguous IP range with one country. That is the same shape as real IP allocation, where countries own blocks of addresses.
  - For an IP it has seen, the tree is exact, because the IP → country dependency from part 2 means it's never ambiguous.
  - For a new IP, it predicts the country of the range the IP falls in.
- **Test set:** a random 20% of rows.
- **Extra checks in `summary.txt`:**
  - The accuracy on test rows whose IP never appears in training.
  - The accuracy of a second split in which no IP is shared between train and test.

  These show whether the model learned IP ranges rather than memorizing IPs.

### Model 2: income (target 35%+)

- **Features considered:** age group, gender, country and the hour of `time_of_day`, one-hot encoded.
- **Test set:** 20% of the data, split by client IP. Both copies of a duplicated request, and every request from the same IP, land on the same side, so the test set contains only unseen requests.
- **Model selection:** sixteen combinations, four models × four feature sets.
  - Models: naive Bayes, logistic regression, a depth-limited decision tree, and gradient boosting.
  - Feature sets: age; age + gender; age + gender + country; and all four.
  - Each is scored with 3-fold cross-validation on the training set, also grouped by IP. The best one is refit on the whole training set and scored once on the test set. On ties, the one with fewer features wins.
- **Context in `summary.txt`:** the "always guess the most common income" baseline, and random guessing (1 / number of income groups).
- **If accuracy is under 35%:** the headers carry little information about income for this run's random seed. Report that, along with the baseline, which shows how much the model learned beyond guessing.

### Results

The results go in `summary.txt` in the bucket. `run_hw6.sh` prints that file and the first rows of both prediction files. From the run on 72,396 requests:

| | Test accuracy | Baseline (most common class) |
|---|---|---|
| Model 1: IP → country | **100.00%** (14,479 test rows) | 0.53% |
| Model 2: → income | **32.54%** (14,464 test rows, IPs unseen in training) | 12.40% |

**Model 1.** The model is 100% accurate even on IPs it never saw in training. That's true both for test rows whose IP isn't in the training set and for a split where no IP is shared at all. So the client assigns each country contiguous IP ranges, and the 965-leaf tree has learned those ranges. It isn't just memorizing addresses.

**Model 2: problems encountered.** The test accuracy is 32.5%, short of the 35% target, though about 2.6× better than guessing.
- Every one of the 16 candidate models and feature sets scored between 32.9% and 33.6% in cross-validation. Age group carries most of the signal; gender, country and hour add under half a point.
- When very different models all hit the same ceiling, the limit is the information in the data for this random seed (528), not the choice of model.
- The grouped split is what keeps the score honest. A plain random row split, which the summary also reports for comparison, scores somewhat higher, but only because most of its test rows have an identical copy in training, a side effect of running both clients with the same seed.
- A different seed for the HW5 clients would produce different data and could move the result either way. This is the "vagaries of the random seed" the assignment mentions.
