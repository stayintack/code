-- Query 1: headline portfolio size and target prevalence.
SELECT
    COUNT(*) AS accounts,
    SUM(default_flag) AS defaults,
    ROUND(AVG(default_flag) * 100.0, 2) AS default_rate_pct
FROM credit_clients;

-- Query 2: outcome rate by most recent repayment status.
SELECT
    pay_0 AS latest_payment_status,
    COUNT(*) AS accounts,
    SUM(default_flag) AS defaults,
    ROUND(AVG(default_flag) * 100.0, 2) AS default_rate_pct
FROM credit_clients
GROUP BY pay_0
ORDER BY pay_0;

-- Query 3: outcome rate by credit-limit band.
SELECT
    CASE
        WHEN limit_bal < 50000 THEN '< 50k'
        WHEN limit_bal < 150000 THEN '50k-149k'
        WHEN limit_bal < 300000 THEN '150k-299k'
        ELSE '300k+'
    END AS credit_limit_band,
    COUNT(*) AS accounts,
    SUM(default_flag) AS defaults,
    ROUND(AVG(default_flag) * 100.0, 2) AS default_rate_pct
FROM credit_clients
GROUP BY credit_limit_band
ORDER BY MIN(limit_bal);
