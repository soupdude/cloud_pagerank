-- CS528 HW6: the HW5 data in third normal form.
--
-- The HW5 table `requests` was not in 3NF. Its key is `id`, but:
--   client_ip -> country     (an IP always comes from the same country)
--   country   -> is_banned   (whether a country is banned depends only on the country)
-- so `country` and `is_banned` depended on the key only transitively, through
-- client_ip. That repeated every country name and banned flag on every request,
-- and allowed contradictions (the same IP stored with two countries).
--
-- The new schema, in database `hw6`, moves each of those facts into a table
-- whose key determines it:
--   countries(country_id -> name, is_banned)
--   client_ips(client_ip -> country_id)
--   requests(request_id -> client_ip, gender, age, income, time_of_day,
--            requested_file, status_code)
--   failed_requests(id -> request_time, requested_file, error_code)  (already 3NF)
--
-- migrate_schema.py runs this file. It is safe to run again: it rebuilds hw6
-- from the HW5 tables, which are left unchanged.

DROP DATABASE IF EXISTS hw6;

CREATE DATABASE hw6 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE hw6.countries (
    country_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name       VARCHAR(64) NOT NULL,
    is_banned  BOOLEAN NOT NULL,
    PRIMARY KEY (country_id),
    UNIQUE KEY uq_countries_name (name)
) ENGINE=InnoDB;

CREATE TABLE hw6.client_ips (
    client_ip  VARCHAR(45) NOT NULL,
    country_id SMALLINT UNSIGNED NULL,         -- NULL: request sent without X-country
    PRIMARY KEY (client_ip),
    CONSTRAINT fk_client_ips_country FOREIGN KEY (country_id)
        REFERENCES hw6.countries (country_id)
) ENGINE=InnoDB;

CREATE TABLE hw6.requests (
    request_id     BIGINT UNSIGNED NOT NULL,   -- same value as hw5.requests.id
    client_ip      VARCHAR(45) NOT NULL,
    gender         VARCHAR(16),
    age            VARCHAR(16),
    income         VARCHAR(16),
    time_of_day    DATETIME NOT NULL,
    requested_file VARCHAR(255),
    status_code    SMALLINT NOT NULL,
    PRIMARY KEY (request_id),
    KEY ix_requests_client_ip (client_ip),
    CONSTRAINT fk_requests_client_ip FOREIGN KEY (client_ip)
        REFERENCES hw6.client_ips (client_ip)
) ENGINE=InnoDB;

CREATE TABLE hw6.failed_requests (
    id             BIGINT UNSIGNED NOT NULL,   -- same value as hw5.failed_requests.id
    request_time   DATETIME NOT NULL,
    requested_file VARCHAR(255),
    error_code     SMALLINT NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB;

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
FROM hw5.requests
WHERE client_ip IS NOT NULL;

-- 4. Failed requests are copied as they are.
INSERT INTO hw6.failed_requests (id, request_time, requested_file, error_code)
SELECT id, request_time, requested_file, error_code
FROM hw5.failed_requests;
