"""CS528 HW6: two models trained on the request data in database hw6.

  Model 1: client IP -> country        (decision tree on the IP as a number)
  Model 2: other fields -> income      (best of several models, chosen by
                                        cross-validation on the training set)

Each model gets a held-out test set. The test-set predictions and a summary
are written to gs://<bucket>/hw6-output/ (or to ./output with --local).

    python models.py              # read hw6, write to the bucket (what the VM runs)
    python models.py --local      # read hw6, write to ./output
    python models.py --input-csv data.csv --local   # no database (for testing)
"""
import argparse
import io
import ipaddress
import pathlib
import time

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, GroupShuffleSplit, cross_val_score, train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier

SEED = 528
TEST_SIZE = 0.2
OUTPUT_PREFIX = "hw6-output"

QUERY = """
SELECT r.request_id, r.client_ip, c.name AS country, r.gender, r.age, r.income,
       r.time_of_day
FROM requests AS r
JOIN client_ips AS i ON i.client_ip = r.client_ip
LEFT JOIN countries AS c ON c.country_id = i.country_id
"""


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------- data --

def load_from_db():
    from dbconn import connect
    with connect(db="hw6") as conn:
        cur = conn.cursor()
        cur.execute(QUERY)
        cols = [d[0] for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def ip_to_int(ip):
    try:
        return int(ipaddress.IPv4Address(str(ip).strip()))
    except ValueError:
        return np.nan  # IPv6 or junk; not produced by the provided client


# ------------------------------------------------------------- model 1 --

def model_country(df, report):
    d = df.dropna(subset=["country", "client_ip"]).copy()
    d["ip_int"] = d["client_ip"].map(ip_to_int)
    d = d.dropna(subset=["ip_int"])
    report.append("MODEL 1: client IP -> country")
    report.append(f"  rows: {len(d)}, distinct IPs: {d.client_ip.nunique()}, "
                  f"countries: {d.country.nunique()}")

    train, test = train_test_split(d, test_size=TEST_SIZE, random_state=SEED)
    X_train, X_test = train[["ip_int"]], test[["ip_int"]]

    # A decision tree on one numeric feature learns split points on the IP
    # number, so each leaf is a contiguous IP range with one country. Grown to
    # full depth it also separates single IPs, so it is exact for IPs it has
    # seen, and assigns an unseen IP to the range it falls into.
    tree = DecisionTreeClassifier(random_state=SEED).fit(X_train, train.country)
    pred = tree.predict(X_test)
    acc = float(np.mean(pred == test.country))

    baseline = DummyClassifier(strategy="most_frequent").fit(X_train, train.country)
    base_acc = float(np.mean(baseline.predict(X_test) == test.country))

    seen = test.client_ip.isin(set(train.client_ip))
    unseen_acc = float(np.mean(pred[~seen.values] == test.country[~seen].values)) \
        if (~seen).any() else float("nan")

    # Harder check: no IP in both train and test, so the tree must generalize
    # from IP ranges instead of recognizing an IP it has already seen.
    gss = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=SEED)
    tr_idx, te_idx = next(gss.split(d, groups=d.client_ip))
    g_tree = DecisionTreeClassifier(random_state=SEED).fit(
        d.iloc[tr_idx][["ip_int"]], d.iloc[tr_idx].country)
    g_acc = float(np.mean(g_tree.predict(d.iloc[te_idx][["ip_int"]]) == d.iloc[te_idx].country))

    report.append(f"  model: decision tree on the IP as a 32-bit integer "
                  f"({tree.get_n_leaves()} leaves, depth {tree.get_depth()})")
    report.append(f"  test set: {len(test)} rows ({TEST_SIZE:.0%} random split)")
    report.append(f"  TEST ACCURACY: {acc:.4%}")
    report.append(f"  most-frequent-country baseline: {base_acc:.2%}")
    report.append(f"  test rows whose IP also appears in training: {seen.mean():.1%}; "
                  f"accuracy on the rest (unseen IPs): {unseen_acc:.2%}")
    report.append(f"  accuracy when no IP is shared between train and test: {g_acc:.2%}")
    report.append("")

    out = pd.DataFrame({
        "client_ip": test.client_ip.values,
        "actual_country": test.country.values,
        "predicted_country": pred,
        "correct": pred == test.country.values,
    })
    return out, acc


# ------------------------------------------------------------- model 2 --

FEATURE_SETS = {
    "age": ["age"],
    "age+gender": ["age", "gender"],
    "age+gender+country": ["age", "gender", "country"],
    "age+gender+country+hour": ["age", "gender", "country", "hour"],
}


def candidate_models(features):
    def onehot(dense=False):
        return ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore",
                                                        sparse_output=not dense),
                                   features)])
    return {
        "naive Bayes": make_pipeline(onehot(), MultinomialNB()),
        "logistic regression": make_pipeline(onehot(), LogisticRegression(max_iter=2000)),
        "decision tree": make_pipeline(onehot(), DecisionTreeClassifier(
            max_depth=12, min_samples_leaf=20, random_state=SEED)),
        "gradient boosting": make_pipeline(onehot(dense=True), HistGradientBoostingClassifier(
            max_iter=100, learning_rate=0.1, early_stopping=True, random_state=SEED)),
    }


def model_income(df, report):
    d = df.dropna(subset=["income", "age", "gender", "country"]).copy()
    d["hour"] = pd.to_datetime(d["time_of_day"]).dt.hour.astype(str)
    report.append("MODEL 2: age, gender, country, hour of day -> income")
    report.append(f"  rows: {len(d)}, income groups: {d.income.nunique()} "
                  f"({', '.join(sorted(d.income.unique()))})")

    # The two clients used the same seed, so every request appears twice.
    # Splitting by client IP keeps both copies (and every request from one IP)
    # on the same side, so the test set never contains a row seen in training.
    gss = GroupShuffleSplit(n_splits=1, test_size=TEST_SIZE, random_state=SEED)
    tr_idx, te_idx = next(gss.split(d, groups=d.client_ip))
    train, test = d.iloc[tr_idx], d.iloc[te_idx]

    cv = GroupKFold(n_splits=3)
    results = []
    for fs_name, features in FEATURE_SETS.items():
        for m_name, model in candidate_models(features).items():
            t = time.time()
            scores = cross_val_score(model, train[features], train.income,
                                     groups=train.client_ip, cv=cv, scoring="accuracy")
            results.append((scores.mean(), fs_name, m_name))
            log(f"  CV {scores.mean():.2%}  {m_name:<20} {fs_name}  ({time.time() - t:.0f}s)")

    # Best CV accuracy first; on (near) ties prefer fewer features.
    results.sort(key=lambda r: (-round(r[0], 4), len(FEATURE_SETS[r[1]])))
    best_cv, best_fs, best_m = results[0]
    features = FEATURE_SETS[best_fs]
    model = candidate_models(features)[best_m].fit(train[features], train.income)
    pred = model.predict(test[features])
    acc = float(np.mean(pred == test.income.values))
    base = DummyClassifier(strategy="most_frequent").fit(train[features], train.income)
    base_acc = float(np.mean(base.predict(test[features]) == test.income.values))

    report.append("  candidates (3-fold cross-validation on the training set, grouped by IP):")
    for score, fs_name, m_name in results:
        report.append(f"    {score:6.2%}  {m_name:<20} features: {fs_name}")
    report.append(f"  chosen: {best_m} on {best_fs}")
    report.append(f"  test set: {len(test)} rows (IPs not seen in training)")
    report.append(f"  TEST ACCURACY: {acc:.2%}")
    report.append(f"  most-frequent-income baseline: {base_acc:.2%}; "
                  f"random guessing: {1 / d.income.nunique():.2%}")

    # For comparison: the same model with a plain random row split. Because the
    # two clients sent identical requests, most test rows then have an exact
    # copy in the training set, which inflates the score.
    r_train, r_test = train_test_split(d, test_size=TEST_SIZE, random_state=SEED)
    r_model = candidate_models(features)[best_m].fit(r_train[features], r_train.income)
    r_acc = float(np.mean(r_model.predict(r_test[features]) == r_test.income.values))
    dup_share = r_test.set_index(["client_ip", "time_of_day"]).index.isin(
        r_train.set_index(["client_ip", "time_of_day"]).index).mean()
    report.append(f"  for comparison, a random row split (not by IP): {r_acc:.2%} "
                  f"({dup_share:.0%} of its test rows have an identical copy in training)")
    if acc < 0.35:
        report.append("  NOTE: below the 35% target on the IP-grouped test set. "
                      "Cross-validation tops out near the same value for every model "
                      "and feature set, so the limit is the signal in the data for this "
                      "seed, not the model. See the README.")
    report.append("")

    out = test[["request_id", "client_ip", "country", "gender", "age", "hour"]].copy()
    out["actual_income"] = test.income.values
    out["predicted_income"] = pred
    out["correct"] = pred == test.income.values
    return out, acc


# -------------------------------------------------------------- output --

def write_outputs(files, local):
    if local:
        folder = pathlib.Path("output")
        folder.mkdir(exist_ok=True)
        for name, text in files.items():
            (folder / name).write_text(text)
            log(f"wrote output/{name}")
        return
    from google.cloud import storage
    from dbconn import BUCKET, PROJECT, credentials
    bucket = storage.Client(project=PROJECT, credentials=credentials()).bucket(BUCKET)
    for name, text in files.items():   # summary.txt last: it signals "done"
        bucket.blob(f"{OUTPUT_PREFIX}/{name}").upload_from_string(
            text, content_type="text/plain")
        log(f"wrote gs://{BUCKET}/{OUTPUT_PREFIX}/{name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="write to ./output, not the bucket")
    parser.add_argument("--input-csv", help="read rows from a CSV instead of the database")
    args = parser.parse_args()

    start = time.time()
    log("loading data")
    df = pd.read_csv(args.input_csv) if args.input_csv else load_from_db()
    log(f"loaded {len(df)} rows")

    report = ["CS528 HW6 model results", f"rows loaded from hw6: {len(df)}", ""]
    log("training model 1 (IP -> country)")
    out1, _ = model_country(df, report)
    log("training model 2 (-> income)")
    out2, _ = model_income(df, report)
    report.append(f"total run time: {time.time() - start:.0f}s")
    summary = "\n".join(report) + "\n"
    print("\n" + summary, flush=True)

    def csv_text(frame):
        buf = io.StringIO()
        frame.to_csv(buf, index=False)
        return buf.getvalue()

    write_outputs({
        "model1_country_test_predictions.csv": csv_text(out1),
        "model2_income_test_predictions.csv": csv_text(out2),
        "summary.txt": summary,
    }, args.local)


if __name__ == "__main__":
    main()
