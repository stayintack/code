# Credit Card Default Risk Scorecard

An end-to-end credit-risk analytics project built around the UCI **Default of Credit Card Clients** dataset. It demonstrates a transparent logistic-regression scorecard, a tree-based benchmark, SQL-based portfolio analysis, and approval-policy trade-offs for a risk/data analyst portfolio.

## Business problem

A card issuer needs to rank applicants by the likelihood of missing a payment in the following month. The target is the source dataset's binary next-month default indicator. The model outputs a probability of default (PD), which is converted into an additive score where a higher score indicates lower predicted risk. Approval cut-offs show how risk appetite changes the share of accounts approved and the observed default rate among those accounts.

This is a demonstration using historical Taiwanese credit-card data from 2005. It is not a production lending model or an estimate of current Australian credit risk. The analysis excludes direct demographic fields from model inputs, but that alone does not establish fairness or legal suitability.

## Dataset

The notebook downloads the public Excel file directly from the [UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients) on first run. No account is required. UCI describes 30,000 observations and six months of repayment status, bill statements and prior payments, alongside account and demographic information. The source workbook and downloaded archive are cached under `data/raw/` and are excluded from Git.

The downloaded records are cleaned by standardising field names, removing exact duplicates and the row identifier, mapping undocumented education and marriage codes into the documented “other” groups, and checking numeric types, missingness and binary target values. The UCI source reports no missing values. Demographic fields (`sex`, `education`, `marriage`, `age`) remain available for descriptive review but are excluded from the models; the retained predictors are credit limit, repayment-status history, bill statements and prior payments.

UCI's dataset is provided under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: Yeh, I. (2009), *Default of Credit Card Clients*, UCI Machine Learning Repository, [DOI: 10.24432/C55S3H](https://doi.org/10.24432/C55S3H).

## Methods

1. **Data quality and EDA:** profile shape, target prevalence, data types, duplicates and documented special codes; chart default prevalence and inspect feature distributions.
2. **SQLite:** load the cleaned portfolio to an in-memory SQLite database and query overall outcomes and default rates across repayment status and other portfolio segments.
3. **Train/test design:** stratified 60%/20%/20% train, validation and test partitions with a fixed seed. Fit bins, WoE values, IV screening and model coefficients using training data only.
4. **WoE/IV:** quantile bins for numeric behavior fields, pooled low-frequency repayment categories, smoothed WoE (`ln(good share / bad share)`) and Information Value. Retain variables with training IV above 0.02; the IV value is a screening heuristic, not evidence of causal value.
5. **Models:** regularised logistic regression on WoE-transformed variables as the interpretable scorecard, compared with an XGBoost classifier using the same behavior inputs and one-hot repayment statuses. No hyperparameter search is performed.
6. **Evaluation:** validation AUC and KS to compare models; one final evaluation on the untouched test partition reports AUC, KS and a confusion matrix at a 0.50 PD cut-off. Threshold analysis is also shown. An illustrative approval rule targets at most a 10% observed default rate among validation-approved accounts; the selected cut-off is then assessed on the test set.
7. **Scorecard:** convert logistic coefficients and WoE bins into additive points, with a base score of 600 at 50:1 good-to-bad odds and 20 points to double the odds.

The threshold table is an empirical sensitivity analysis, not a recommended Australian credit policy. In a real decision system, cut-offs need an explicit cost, affordability and loss framework, probability calibration and out-of-time validation.

## Results

The notebook was executed end to end on the downloaded UCI file with the fixed random seed. Results are:

| Metric | Logistic scorecard | XGBoost benchmark |
| --- | ---: | ---: |
| Validation ROC AUC | 0.7617 | 0.7795 |
| Validation KS | 0.4040 | 0.4247 |
| Test ROC AUC | 0.7567 | 0.7779 |
| Test KS | 0.3978 | 0.4317 |

The logistic model retained 13 of 19 behaviour features at IV > 0.02. With an illustrative 10% validation bad-rate appetite, the selected PD cut-off was 0.140. On the untouched test set this cut-off approved 46.8% of accounts; 9.6% of approved accounts defaulted, and those approvals represented 20.3% of all test defaults. The XGBoost benchmark ranked better on this split, while the logistic model provides an additive points table. These figures should be read with the dataset's age, geography and sampling limitations in mind.

On the test set, the stricter 0.10 PD cut-off approved 19.9% of accounts with a 7.4% default rate among approvals; a looser 0.30 cut-off approved 79.9% with a 14.1% default rate. The notebook shows the full range and default capture at each point.

## Run it

Python 3.12 is recommended. From the repository root:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
jupyter lab notebooks/credit_default_risk.ipynb
```

Run cells from top to bottom. On first run, the notebook downloads the workbook from UCI and caches it in `data/raw/`; later runs use the cached copy. A working internet connection is needed only for that first download. The notebook was executed end to end on Python 3.12.

## Project structure

```text
.
├── notebooks/credit_default_risk.ipynb  # Executed analysis and model results
├── sql/eda_queries.sql                   # SQLite portfolio queries used in the notebook
├── src/credit_risk.py                    # Data loading, WoE/IV, scorecard and policy utilities
├── data/raw/                             # Download cache (gitignored)
└── requirements.txt
```

## Conclusion and limitations

The logistic model provides a reviewable PD ranking and additive points table; XGBoost is included as a nonlinear benchmark. The approval table makes the risk/coverage trade-off explicit so a decision-maker can compare policy cut-offs. The notebook's results support a portfolio analytics demonstration, not a live credit decision.

The sample is from Taiwan in 2005, its outcome describes next-month default among existing card clients rather than applicant performance, and a random split does not test future-period drift. It cannot establish performance for Australia. Before practical use, a lender would need representative Australian application and repayment data, out-of-time and external validation, PD calibration, subgroup/fairness review, privacy controls, explainability and adverse-action processes, affordability and responsible-lending assessment, and ongoing drift and outcomes monitoring.
