# Credit Card Default Risk Scorecard

An end-to-end credit-risk analytics project built around the UCI **Default of Credit Card Clients** dataset. It demonstrates data quality checks, SQLite portfolio analysis, monotonic WoE/IV feature screening, a logistic-regression scorecard, an XGBoost benchmark, approval-policy trade-offs, and a reusable applicant-scoring interface.

## Business problem

A card issuer needs to rank accounts by the likelihood of missing a payment in the following month. The model estimates probability of default (PD), then converts logistic-regression log-odds into additive points where higher scores indicate lower predicted risk. Approval cut-offs make the coverage/default-rate trade-off visible.

This is a portfolio demonstration using historical Taiwanese credit-card data from 2005. It is not a production lending model or an estimate of current Australian credit risk. Demographic fields are available for descriptive review but excluded from the model; that choice alone does not establish fairness or legal suitability.

## Dataset and cleaning

The notebook downloads the public Excel workbook directly from the [UCI Machine Learning Repository](https://archive.ics.uci.edu/dataset/350/defaultofcreditcardclients) on first run; no account is required. UCI reports 30,000 source observations. The loader removes duplicate IDs, removes the ID field, then drops 35 exact duplicate feature/outcome rows. This leaves **29,965 unique modeling profiles** and prevents identical records from appearing on both sides of the train/test split. The source file is cached under `data/raw/`, which is created automatically and excluded from Git.

The loader standardises field names, maps education and marriage codes to the documented “other” groups, and validates numeric types, missingness, and the binary target. The UCI source reports no missing values. The dataset is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Attribution: Yeh, I. (2009), *Default of Credit Card Clients*, UCI Machine Learning Repository, [DOI: 10.24432/C55S3H](https://doi.org/10.24432/C55S3H).

## Methods

1. **Data quality and EDA:** inspect row/field profiles, target rate, special-code frequencies, repayment-status default rates, and feature distributions.
2. **SQLite:** load the cleaned portfolio into an in-memory SQLite database and query overall outcomes and default rates across repayment-status and demographic segments.
3. **Train/validation/test:** stratified 60%/20%/20% split with a fixed seed. Binning, WoE values, IV and correlation screening, and model fitting use training data only.
4. **WoE/IV:** use quantile bins for numeric behavior fields and pooled repayment-status groups. Adjacent groups are merged to make training bad rates monotonic. Calculate smoothed WoE as `ln(good share / bad share)` and IV; retain IV above 0.02. A training-only absolute Spearman correlation screen at 0.65 removes redundant WoE features, keeping the higher-IV feature in each correlated pair. These are screening heuristics, not causal evidence.
5. **Models:** regularised logistic regression on WoE features is the interpretable scorecard; XGBoost is the tree-based benchmark. Both use behavioral inputs, with one-hot repayment statuses for XGBoost. No hyperparameter search is performed.
6. **Feature ablation:** compare removing `pay_amt5` and `pay_amt6` on validation. The two-feature reduction changed AUC by 0.0002 and KS by 0.0004, so the simpler nine-feature scorecard is used.
7. **Evaluation:** report validation and final holdout AUC/KS, confusion-matrix counts at a 0.50 PD cut-off, and approval-policy sensitivity. The illustrative policy chooses a cut-off on validation to keep the observed bad rate among approved accounts at or below 9%, then checks it on the test split. The 9% appetite (a one-point buffer below an earlier 10% target) was adopted after an earlier run showed that the 10% validation cut-off exceeded 10% on test, so the test split informed this one policy choice and is not fully untouched for it. Model fitting and feature selection never used the test split.
8. **Scorecard and inference:** convert logistic coefficients and WoE bins into additive points. Score 500 represents the training portfolio's good-to-bad odds (about 3.52:1); 20 points doubles those odds. Save the fitted encoder and model to `models/credit_default_scorecard.joblib`. `score_new_applicants()` requires only the scorecard's selected raw fields, rejects missing, non-numeric or out-of-range values (repayment codes must be integers from -2 to 9, credit limits positive, payment amounts non-negative), and returns PD plus an integer score.

The source documents `-1` as paid duly and positive repayment codes as months of delay. Its notes do not define observed codes `-2` and `0`; the notebook preserves and reports them without assigning unsupported business meanings. In `pay_3`, `pay_4`, and `pay_6`, code 1 is pooled with the non-positive codes and codes 2+ are grouped together. That monotonic pooling improves stability but loses some delay-level detail; EDA retains the original category breakdowns.

## Results

The checked-in notebook includes outputs from a full execution using the pinned environment and fixed random seed.

| Metric | Logistic scorecard | XGBoost benchmark |
| --- | ---: | ---: |
| Validation ROC AUC | 0.7679 | 0.7852 |
| Validation KS | 0.4129 | 0.4382 |
| Test ROC AUC | 0.7542 | 0.7702 |
| Test KS | 0.3974 | 0.4175 |

At the illustrative 9% validation bad-rate appetite, the selected PD cut-off was **0.130**. On validation it approved 40.5% of accounts with an 8.69% bad rate. On the test split it approved **39.9%**, with a **9.4%** bad rate among approved accounts, covering 17.0% of all test defaults. The test score range was 407–540, with score 500 anchored to training good-to-bad odds.

For reference, a 0.10 PD test cut-off approved 21.0% of accounts with an 8.8% bad rate; a 0.15 cut-off approved 52.3% with a 10.7% bad rate; a 0.30 cut-off approved 79.6% with a 14.0% bad rate. XGBoost ranked better on this split, while logistic regression provides the additive, reviewable scorecard. XGBoost AUC can vary by around 0.001 across operating systems and native builds; the displayed result is from the Windows run.

These results are specific to this historical sample and split. They are not a recommended Australian lending policy; real cut-offs require explicit cost, affordability and loss frameworks, calibrated PDs and out-of-time validation.

## Run it

**Python 3.12 or newer is required.** From the repository root:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
jupyter lab notebooks/credit_default_risk.ipynb
```

Run cells from top to bottom. The first run downloads the UCI workbook and caches it in `data/raw/`; later runs use the cached copy. A working internet connection is needed only for the first download. The notebook saves a reusable scorecard bundle in `models/`; the generated binary is ignored by Git and can be reproduced by rerunning the notebook.

Run the unit tests with:

```bash
python -m unittest discover -s tests -v
```

To score a new applicant after running the notebook, pass a DataFrame containing the nine selected fields (`pay_0`, `pay_3`, `pay_4`, `pay_6`, `limit_bal`, `pay_amt1`–`pay_amt4`); extra columns such as a client ID are ignored:

```python
import joblib
from src.credit_risk import score_new_applicants

bundle = joblib.load("models/credit_default_scorecard.joblib")
scores = score_new_applicants(
    applicants,
    encoder=bundle["encoder"],
    model=bundle["model"],
    selected_features=list(bundle["selected_features"]),
    base_score=bundle["base_score"],
    base_good_odds=bundle["base_good_odds"],
    points_to_double_odds=bundle["points_to_double_odds"],
)
```

The bundle is a joblib (pickle) file: load only bundles you generated yourself, because loading an untrusted pickle can execute arbitrary code.

## Project structure

```text
.
├── notebooks/credit_default_risk.ipynb     # Executed analysis, tables and plots
├── sql/eda_queries.sql                     # SQLite portfolio queries
├── src/credit_risk.py                      # Data loading, WoE/IV, scoring and policy utilities
├── src/__init__.py
├── tests/test_credit_risk.py               # Cleaning and inference tests
├── models/credit_default_scorecard.joblib  # Generated by notebook; gitignored
├── data/raw/                               # Created on first run; downloaded data is gitignored
├── requirements.txt
└── .gitignore
```

## Conclusion and limitations

The logistic model gives an inspectable PD ranking and additive points table. XGBoost provides a nonlinear benchmark, and the approval table makes the risk/coverage trade-off explicit. On this split XGBoost has higher AUC/KS; the scorecard remains useful where traceability and review of individual bin contributions matter.

The sample is from Taiwan in 2005, and its outcome describes next-month default among existing card clients rather than applicant performance. A random split does not test future-period drift, and the results cannot establish performance for Australia. Practical use would require representative Australian application and repayment data, out-of-time and external validation, PD calibration, subgroup/fairness review, privacy controls, explainability and adverse-action processes, affordability and responsible-lending assessment, and ongoing drift and outcomes monitoring.
