# Credit Card Default Risk Scorecard

An end-to-end credit-risk analytics project built around the UCI **Default of Credit Card Clients** dataset. It demonstrates data quality checks, SQLite portfolio analysis, monotonic WoE/IV feature screening, a logistic-regression scorecard, an XGBoost benchmark, and approval-policy trade-offs for an Australian risk/data analyst portfolio.

## Business problem

A card issuer needs to rank accounts by the likelihood of missing a payment in the following month. The model estimates probability of default (PD), then converts logistic-regression log-odds into additive points where higher scores indicate lower predicted risk. Approval cut-offs make the coverage/default-rate trade-off visible.

This is a portfolio demonstration using historical Taiwanese credit-card data from 2005. It is not a production lending model or an estimate of current Australian credit risk. Demographic fields are available for descriptive review but excluded from the model; that choice alone does not establish fairness or legal suitability.

## Dataset and cleaning

The notebook downloads the public Excel workbook directly from the [UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/350/defaultofcreditcardclients) on first run; no account is required. UCI reports 30,000 source observations. The loader removes duplicate IDs, removes the ID field, then drops 35 exact duplicate feature/outcome rows. This leaves **29,965 unique modeling profiles** and avoids identical rows appearing on both sides of the train/test split. The source file is cached under `data/raw/`, which is created automatically and excluded from Git.

The loader standardises field names, maps education and marriage codes to the documented “other” groups, and validates numeric types, missingness, and the binary target. The UCI source reports no missing values. The dataset is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: Yeh, I. (2009), *Default of Credit Card Clients*, UCI Machine Learning Repository, [DOI: 10.24432/C55S3H](https://doi.org/10.24432/C55S3H).

## Methods

1. **Data quality and EDA:** inspect row/field profiles, target rate, special-code frequencies and feature distributions. The notebook includes target prevalence, latest repayment-status default rates, and balance/statement/payment distributions.
2. **SQLite:** load the cleaned portfolio into an in-memory SQLite database and query overall outcomes and default rates across repayment-status and demographic segments.
3. **Train/validation/test:** stratified 60%/20%/20% split with a fixed seed. Binning, WoE values, IV screening, correlation screening, and model fitting use training data only.
4. **WoE/IV:** use quantile bins for numeric behavior fields and pooled repayment-status groups. Adjacent groups are merged to make training bad rates monotonic. Calculate smoothed WoE as `ln(good share / bad share)` and IV; retain IV above 0.02. A training-only absolute Spearman correlation screen at 0.65 removes redundant WoE features, keeping the higher-IV feature in each correlated pair. IV and correlation are screening heuristics, not causal evidence.
5. **Models:** regularised logistic regression on WoE features is the interpretable scorecard; XGBoost is the tree-based benchmark. Both use behavioral inputs, with one-hot repayment statuses for XGBoost. No hyperparameter search is performed.
6. **Evaluation:** report validation and final holdout AUC/KS, confusion-matrix counts at a 0.50 PD cut-off, and approval-policy sensitivity. The illustrative policy chooses a cut-off on validation to keep observed bad rate among approved accounts at or below 10%, then checks it on the untouched test split.
7. **Scorecard:** convert logistic coefficients and WoE bins into additive points. Score 500 represents the training portfolio's good-to-bad odds (about 3.52:1); 20 points doubles the good-to-bad odds. The bin-level table shows all features, training account counts, bad rates, IV contributions and points. Monotonicity is asserted in the notebook.

UCI defines repayment code `-1` as paid duly and positive values as months of payment delay. The UCI variable notes do not define observed codes `-2` and `0`; the notebook preserves them, shows their counts, and treats them only as non-positive codes when constructing pooled model bins rather than assigning unsupported business meanings.

## Results

The checked-in notebook includes outputs from a full execution using the pinned environment and fixed random seed.

| Metric | Logistic scorecard | XGBoost benchmark |
| --- | ---: | ---: |
| Validation ROC AUC | 0.7681 | 0.7852 |
| Validation KS | 0.4133 | 0.4382 |
| Test ROC AUC | 0.7541 | 0.7702 |
| Test KS | 0.3972 | 0.4175 |

The logistic scorecard retained **11 of 19** behavior features after IV and correlation screening; redundant `pay_2` and `pay_5` were removed. At the illustrative 10% validation bad-rate appetite, the selected PD cut-off was **0.150**. On validation it approved 52.3% of accounts with a 9.8% bad rate. On the untouched test split it approved **52.0%**, with a **10.6%** bad rate among approved accounts, covering 24.9% of all test defaults. The test score range was 407–541, with score 500 anchored to training good-to-bad odds.

The test-set sensitivity analysis shows the trade-off: a 0.10 PD cut-off approved 21.1% of accounts with an 8.8% bad rate; a 0.15 cut-off approved 52.0% with a 10.6% bad rate; a 0.30 cut-off approved 79.5% with a 14.0% bad rate. XGBoost ranked better on this split, while logistic regression provides the additive, reviewable scorecard. The notebook contains the confusion matrices for both models and the full policy table.

These results are specific to this historical sample and split. They are not a recommended Australian lending policy; real cut-offs require explicit cost, affordability and loss frameworks, calibrated PDs and out-of-time validation.

## Run it

**Python 3.12 or newer is required.** The pinned NumPy, SciPy and XGBoost releases do not support Python 3.11. From the repository root:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
jupyter lab notebooks/credit_default_risk.ipynb
```

Run cells from top to bottom. The first run downloads the UCI workbook and caches it in `data/raw/`; later runs use the cached copy. A working internet connection is needed only for the first download. The checked-in notebook was executed end to end with Python 3.12.

## Project structure

```text
.
├── notebooks/credit_default_risk.ipynb  # Executed analysis, tables and plots
├── sql/eda_queries.sql                   # SQLite portfolio queries
├── src/credit_risk.py                    # Data loading, WoE/IV, scorecard and policy utilities
├── data/raw/                              # Created on first run; downloaded data is gitignored
├── requirements.txt
└── .gitignore
```

## Conclusion and limitations

The logistic model gives an inspectable PD ranking and additive points table. XGBoost provides a nonlinear benchmark, and the approval table makes the risk/coverage trade-off explicit. On this split XGBoost has higher AUC/KS; the scorecard remains useful where traceability and review of individual bin contributions matter.

The sample is from Taiwan in 2005, and its outcome describes next-month default among existing card clients rather than applicant performance. A random split does not test future-period drift, and the results cannot establish performance for Australia. Practical use would require representative Australian application and repayment data, out-of-time and external validation, PD calibration, subgroup/fairness review, privacy controls, explainability and adverse-action processes, affordability and responsible-lending assessment, and ongoing drift and outcomes monitoring.
