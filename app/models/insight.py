"""Pydantic request/response models for POST /v1/ffr_insight."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.common import CTAObject, FfrRequestMetadata, FfrScreenData, ValidationDetail, validate_pillar_fields

INSIGHTS_API_VERSION = "1.0.0"


# ── Finbox nested objects ─────────────────────────────────────────────────────

class BillDetail(BaseModel):
    """Single billing period detail for a bill account."""

    model_config = ConfigDict(extra="allow")

    bill_amount: Optional[float] = Field(None, description="Bill amount for the period.")
    bill_status: Optional[str] = Field(None, description='Status string, e.g. `"bill_paid"`.')
    bill_paid_amt: Optional[float] = Field(None, description="Amount actually paid.")
    bill_status_inbox_date: Optional[str] = Field(None, description="Date the bill status was received (YYYY-MM-DD).")
    bill_due_date: Optional[str] = Field(None, description="Payment due date (YYYY-MM-DD), null for prepaid.")


class BillAccount(BaseModel):
    """One bill account entry inside ``bill_profile``."""

    model_config = ConfigDict(extra="allow")

    bill_provider: Optional[str] = Field(None, description='Provider name, e.g. `"jio"`, `"maharashtra electricity"`.')
    bill_category: Optional[str] = Field(None, description='Category, e.g. `"phone"`, `"electricity"`.')
    bill_acc_number: Optional[str] = Field(None, description="Account identifier.")
    billing_plan: Optional[str] = Field(None, description='Billing plan, e.g. `"prepaid"`, `"postpaid"`.')
    bill_detail_m1: Optional[BillDetail] = Field(None, description="Most recent month billing detail.")


class BankAccountProfile(BaseModel):
    """Single bank account entry inside ``all_account_profile``."""

    model_config = ConfigDict(extra="allow")

    acc_no: Optional[str] = Field(None, description="Account identifier string.")
    bank_name: Optional[str] = Field(None, description="Bank name.")
    latest_balance: Optional[float] = Field(None, description="Latest available balance (INR).")
    cnt_credits_c30: Optional[int] = Field(None, description="Credit transaction count in last 30 days.")
    amt_credits_c30: Optional[float] = Field(None, description="Total credit amount in last 30 days (INR).")
    cnt_debits_c30: Optional[int] = Field(None, description="Debit transaction count in last 30 days.")
    amt_debits_c30: Optional[float] = Field(None, description="Total debit amount in last 30 days (INR).")
    avg_balance_c30: Optional[float] = Field(None, description="Average balance over last 30 days (INR).")


class LoanAccount(BaseModel):
    """Single loan entry inside ``loan_profile``."""

    model_config = ConfigDict(extra="allow")

    loan_acc_number: Optional[str] = Field(None, description="Loan account number.")
    lender: Optional[str] = Field(None, description='Lender name, e.g. `"kotak"`, `"home credit"`.')
    amt_loan_acc: Optional[float] = Field(None, description="Loan principal amount (INR).")
    loan_type: Optional[str] = Field(None, description='Loan type, e.g. `"two_wheeler_loan"`, `"home_loan"`.')
    emi_loan_acc: Optional[float] = Field(None, description="Monthly EMI for this loan (INR).")
    amt_delinquency_acc: Optional[float] = Field(None, description="Outstanding delinquency amount.")
    max_dpd: Optional[int] = Field(None, description="Maximum days past due.")
    cnt_delinquncy_acc: Optional[int] = Field(None, description="Number of delinquency events.")


# ── Insight Finbox features model ─────────────────────────────────────────────

class InsightFinboxFeatures(BaseModel):
    """Finbox feature set for the insights API.

    Contains hundreds of flat key-value metrics plus several structured
    sub-objects. All fields are optional. Unknown keys are accepted via
    ``extra="allow"`` to remain forward-compatible with new Finbox features.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # ── Structured sub-objects ──
    category_spending_profile: Optional[Dict[str, Any]] = Field(
        None,
        description="Per-category monthly spend breakdown. Keys follow the pattern "
        "`total_{essential|discretionary}_spends_{category}_m{0-6}`.",
    )
    expense_profile_merchants: Optional[Dict[str, Any]] = Field(
        None,
        description="Merchant-level transaction counts, amounts, and percentages "
        "(e.g. `cnt_txns_zomato_v3_c30`, `amt_txns_amazon_v3_c30`).",
    )
    bill_profile: Optional[Dict[str, BillAccount]] = Field(
        None,
        description="Bill account profiles keyed by `bill_acc1`, `bill_acc2`, etc.",
    )
    all_account_profile: Optional[Dict[str, BankAccountProfile]] = Field(
        None,
        description="Bank account profiles keyed by `acc0`, `acc1`, etc.",
    )
    loan_profile: Optional[Dict[str, LoanAccount]] = Field(
        None,
        description="Loan account profiles keyed by `loan_acc1`, `loan_acc2`, etc.",
    )

    # ── Aggregate spend totals (m0–m6) ──
    total_essential_spend_m0: Optional[float] = Field(None, description="Total essential spend, current month.")
    total_essential_spend_m1: Optional[float] = Field(None, description="Total essential spend, month-1.")
    total_essential_spend_m2: Optional[float] = Field(None, description="Total essential spend, month-2.")
    total_essential_spend_m3: Optional[float] = Field(None, description="Total essential spend, month-3.")
    total_essential_spend_m4: Optional[float] = Field(None, description="Total essential spend, month-4.")
    total_essential_spend_m5: Optional[float] = Field(None, description="Total essential spend, month-5.")
    total_essential_spend_m6: Optional[float] = Field(None, description="Total essential spend, month-6.")
    total_discretionary_spend_m0: Optional[float] = Field(None, description="Total discretionary spend, current month.")
    total_discretionary_spend_m1: Optional[float] = Field(None, description="Total discretionary spend, month-1.")
    total_discretionary_spend_m2: Optional[float] = Field(None, description="Total discretionary spend, month-2.")
    total_discretionary_spend_m3: Optional[float] = Field(None, description="Total discretionary spend, month-3.")
    total_discretionary_spend_m4: Optional[float] = Field(None, description="Total discretionary spend, month-4.")
    total_discretionary_spend_m5: Optional[float] = Field(None, description="Total discretionary spend, month-5.")
    total_discretionary_spend_m6: Optional[float] = Field(None, description="Total discretionary spend, month-6.")
    amt_debit_txn_m0: Optional[float] = Field(None, description="Total debit transaction amount, current month.")
    amt_debit_txn_m1: Optional[float] = Field(None, description="Total debit transaction amount, month-1.")
    amt_debit_txn_m2: Optional[float] = Field(None, description="Total debit transaction amount, month-2.")
    amt_debit_txn_m3: Optional[float] = Field(None, description="Total debit transaction amount, month-3.")
    amt_debit_txn_m4: Optional[float] = Field(None, description="Total debit transaction amount, month-4.")
    amt_debit_txn_m5: Optional[float] = Field(None, description="Total debit transaction amount, month-5.")
    amt_debit_txn_m6: Optional[float] = Field(None, description="Total debit transaction amount, month-6.")
    amt_debit_wo_transf_m0: Optional[float] = Field(None, description="Debit amount excluding transfers, current month.")
    amt_debit_wo_transf_m1: Optional[float] = Field(None, description="Debit amount excluding transfers, month-1.")
    amt_debit_wo_transf_m2: Optional[float] = Field(None, description="Debit amount excluding transfers, month-2.")
    amt_debit_wo_transf_m3: Optional[float] = Field(None, description="Debit amount excluding transfers, month-3.")
    amt_debit_wo_transf_m4: Optional[float] = Field(None, description="Debit amount excluding transfers, month-4.")
    amt_debit_wo_transf_m5: Optional[float] = Field(None, description="Debit amount excluding transfers, month-5.")
    amt_debit_wo_transf_m6: Optional[float] = Field(None, description="Debit amount excluding transfers, month-6.")

    # ── Periodic spend spikes ──
    festival_spend_pct_c30: Optional[float] = Field(None, description="Festival spend percentage, last 30 days.")
    festival_spend_pct_c90: Optional[float] = Field(None, description="Festival spend percentage, last 90 days.")
    late_night_spend_pct_c30: Optional[float] = Field(None, description="Late-night spend percentage, last 30 days.")
    late_night_spend_pct_c90: Optional[float] = Field(None, description="Late-night spend percentage, last 90 days.")
    post_salary_spend_pct_c30: Optional[float] = Field(None, description="Post-salary spend percentage, last 30 days.")
    post_salary_spend_pct_c90: Optional[float] = Field(None, description="Post-salary spend percentage, last 90 days.")
    pre_salary_spend_pct_c30: Optional[float] = Field(None, description="Pre-salary spend percentage, last 30 days.")
    pre_salary_spend_pct_c90: Optional[float] = Field(None, description="Pre-salary spend percentage, last 90 days.")
    weekend_spend_pct_c30: Optional[float] = Field(None, description="Weekend spend percentage, last 30 days.")
    weekend_spend_pct_c90: Optional[float] = Field(None, description="Weekend spend percentage, last 90 days.")

    # ── Subscription features ──
    amt_all_subscriptions_c360: Optional[float] = Field(None, description="Total subscription spend in last 360 days.")
    cnt_all_subscriptions_c360: Optional[int] = Field(None, description="Total subscription count in last 360 days.")
    cnt_streaming_subscriptions_c360: Optional[int] = Field(None, description="Streaming subscription count.")
    cnt_music_subscriptions_c360: Optional[int] = Field(None, description="Music subscription count.")
    cnt_food_delivery_subscriptions_c360: Optional[int] = Field(None, description="Food delivery subscription count.")
    cnt_ecom_subscriptions_c360: Optional[int] = Field(None, description="E-commerce subscription count.")
    cnt_dating_apps_subscriptions_c360: Optional[int] = Field(None, description="Dating app subscription count.")
    cnt_merchant_tools_subscriptions_c360: Optional[int] = Field(None, description="Merchant tools subscription count.")
    cnt_premium_apps_subscriptions_c360: Optional[int] = Field(None, description="Premium app subscription count.")
    cnt_productivity_subscriptions_c360: Optional[int] = Field(None, description="Productivity subscription count.")
    redundant_streaming_subscriptions_c360: Optional[int] = Field(None, description="Redundant streaming subscription count.")
    redundant_music_subscriptions_c360: Optional[int] = Field(None, description="Redundant music subscription count.")
    redundant_food_delivery_subscriptions_c360: Optional[int] = Field(None, description="Redundant food delivery subscription count.")
    redundant_ecom_subscriptions_c360: Optional[int] = Field(None, description="Redundant e-commerce subscription count.")
    redundant_dating_apps_subscriptions_c360: Optional[int] = Field(None, description="Redundant dating apps subscription count.")
    redundant_merchant_tools_subscriptions_c360: Optional[int] = Field(None, description="Redundant merchant tools subscription count.")
    redundant_premium_apps_subscriptions_c360: Optional[int] = Field(None, description="Redundant premium apps subscription count.")
    redundant_productivity_subscriptions_c360: Optional[int] = Field(None, description="Redundant productivity subscription count.")
    subscription_spend_pct_c360: Optional[float] = Field(None, description="Subscription spend as a percentage of total spend.")

    # ── UPI features ──
    avg_monthly_amt_debits_upi_3m: Optional[float] = Field(None, description="Average monthly UPI debit amount over 3 months.")
    max_amt_debits_upi_3m: Optional[float] = Field(None, description="Max single UPI debit amount over 3 months.")
    amt_total_debits_upi_3m: Optional[float] = Field(None, description="Total UPI debit amount over 3 months.")
    cnt_total_debits_upi_3m: Optional[int] = Field(None, description="Total UPI debit count over 3 months.")
    cnt_total_debits_upi_gt_5k_3m: Optional[int] = Field(None, description="UPI debits > 5k count over 3 months.")
    cnt_total_debits_upi_lt_100_3m: Optional[int] = Field(None, description="UPI debits < 100 count over 3 months.")
    avg_monthly_cnt_credits_upi_3m: Optional[float] = Field(None, description="Average monthly UPI credit count over 3 months.")
    avg_monthly_cnt_debits_upi_3m: Optional[float] = Field(None, description="Average monthly UPI debit count over 3 months.")
    ticket_size_credits_upi_3m: Optional[float] = Field(None, description="Average UPI credit ticket size over 3 months.")
    ticket_size_debits_upi_3m: Optional[float] = Field(None, description="Average UPI debit ticket size over 3 months.")
    ticket_size_txn_upi_3m: Optional[float] = Field(None, description="Average UPI transaction ticket size over 3 months.")
    amt_total_debits_upi_m1: Optional[float] = Field(None, description="UPI debit amount, month-1.")
    amt_total_debits_upi_m2: Optional[float] = Field(None, description="UPI debit amount, month-2.")
    amt_total_debits_upi_m3: Optional[float] = Field(None, description="UPI debit amount, month-3.")
    cnt_total_debits_upi_m1: Optional[int] = Field(None, description="UPI debit count, month-1.")
    cnt_total_debits_upi_m2: Optional[int] = Field(None, description="UPI debit count, month-2.")
    cnt_total_debits_upi_m3: Optional[int] = Field(None, description="UPI debit count, month-3.")

    # ── Income seed features ──
    calculated_income_amount_v4: Optional[float] = Field(None, description="Finbox-calculated income amount (INR).")
    calculated_income_profession_type_v4: Optional[str] = Field(None, description='Profession type, e.g. `"gig_worker"`, `"salaried"`.')
    calculated_income_confidence_v4: Optional[str] = Field(None, description='Confidence level, e.g. `"high"`, `"medium"`, `"low"`.')
    amt_credit_txn_c180: Optional[float] = Field(None, description="Total credit transactions, last 180 days.")
    amt_credit_txn_c30: Optional[float] = Field(None, description="Total credit transactions, last 30 days.")
    amt_credit_txn_c90: Optional[float] = Field(None, description="Total credit transactions, last 90 days.")
    amt_credit_txn_m0: Optional[float] = Field(None, description="Credit transaction amount, current month.")
    amt_credit_txn_m1: Optional[float] = Field(None, description="Credit transaction amount, month-1.")
    amt_credit_txn_m2: Optional[float] = Field(None, description="Credit transaction amount, month-2.")
    amt_credit_txn_m3: Optional[float] = Field(None, description="Credit transaction amount, month-3.")
    amt_credit_txn_m4: Optional[float] = Field(None, description="Credit transaction amount, month-4.")
    amt_credit_txn_m5: Optional[float] = Field(None, description="Credit transaction amount, month-5.")
    amt_credit_txn_m6: Optional[float] = Field(None, description="Credit transaction amount, month-6.")

    # ── Account overview ──
    all_acc_av_balance_c90: Optional[float] = Field(None, description="Average balance across all accounts, last 90 days.")
    all_acc_latest_balance_c90: Optional[float] = Field(None, description="Latest balance across all accounts.")
    surplus: Optional[float] = Field(None, description="Monthly surplus (income minus expenses) in INR.")

    # ── EMI by loan type (m0–m12 per type) — representative fields ──
    total_emi_loan_all_acc: Optional[float] = Field(None, description="Current total EMI across all loan accounts.")
    total_emi_all_acc_m0123: Optional[float] = Field(None, description="Aggregate EMI for months 0–3 across all accounts.")
    total_emi_loan_all_acc_c30: Optional[float] = Field(None, description="Total EMI, last 30 days.")
    total_emi_loan_all_acc_c60: Optional[float] = Field(None, description="Total EMI, last 60 days.")
    total_emi_loan_all_acc_c90: Optional[float] = Field(None, description="Total EMI, last 90 days.")
    total_emi_loan_all_acc_c180: Optional[float] = Field(None, description="Total EMI, last 180 days.")
    total_emi_loan_all_acc_c360: Optional[float] = Field(None, description="Total EMI, last 360 days.")

    # ── Loan disbursement ──
    cnt_active_loan_accounts_m1: Optional[int] = Field(None, description="Active loan account count as of month-1.")
    cnt_active_loan_disbursed_gt_100k: Optional[int] = Field(None, description="Active loans > 1 lakh count.")
    loan_disbursed_latest_date: Optional[str] = Field(None, description="Date of most recent loan disbursement.")
    cnt_loan_disbursed_last_6mo: Optional[int] = Field(None, description="Loans disbursed in the last 6 months.")
    cnt_loan_disbursed_gt_100k: Optional[int] = Field(None, description="Loans disbursed > 1 lakh count.")

    # ── Delinquency ──
    cnt_delinquncy_loan_c30: Optional[int] = Field(None, description="Loan delinquency count, last 30 days.")
    cnt_delinquncy_loan_c90: Optional[int] = Field(None, description="Loan delinquency count, last 90 days.")
    cnt_delinquncy_loan_c180: Optional[int] = Field(None, description="Loan delinquency count, last 180 days.")
    cnt_delinquncy_loan_c360: Optional[int] = Field(None, description="Loan delinquency count, last 360 days.")
    amt_delinquncy_loan_c30: Optional[float] = Field(None, description="Loan delinquency amount, last 30 days.")
    amt_delinquncy_loan_c90: Optional[float] = Field(None, description="Loan delinquency amount, last 90 days.")
    amt_delinquncy_loan_c180: Optional[float] = Field(None, description="Loan delinquency amount, last 180 days.")
    amt_delinquncy_loan_c360: Optional[float] = Field(None, description="Loan delinquency amount, last 360 days.")
    cnt_delinquncy_cc_c30: Optional[int] = Field(None, description="Credit card delinquency count, last 30 days.")
    cnt_delinquncy_cc_c90: Optional[int] = Field(None, description="Credit card delinquency count, last 90 days.")
    cnt_delinquncy_cc_c180: Optional[int] = Field(None, description="Credit card delinquency count, last 180 days.")
    cnt_delinquncy_cc_c360: Optional[int] = Field(None, description="Credit card delinquency count, last 360 days.")
    amt_delinquncy_cc_c30: Optional[float] = Field(None, description="Credit card delinquency amount, last 30 days.")
    amt_delinquncy_cc_c90: Optional[float] = Field(None, description="Credit card delinquency amount, last 90 days.")
    amt_delinquncy_cc_c180: Optional[float] = Field(None, description="Credit card delinquency amount, last 180 days.")
    amt_delinquncy_cc_c360: Optional[float] = Field(None, description="Credit card delinquency amount, last 360 days.")

    # ── Credit card features ──
    cc_utilisation: Optional[float] = Field(None, description="Credit card utilisation ratio.")
    cc_bill_latest_date: Optional[str] = Field(None, description="Date of latest CC bill.")
    cc_latest_bill_date: Optional[str] = Field(None, description="Alias for latest CC bill date.")

    # ── Loan flags ──
    loan_applications_flag_c30: Optional[bool] = Field(None, description="Loan application detected in last 30 days.")
    loan_applications_flag_c90: Optional[bool] = Field(None, description="Loan application detected in last 90 days.")
    loan_applications_flag_c180: Optional[bool] = Field(None, description="Loan application detected in last 180 days.")
    loan_applications_flag_c360: Optional[bool] = Field(None, description="Loan application detected in last 360 days.")
    loan_approval_sms_flag_c30_v2: Optional[bool] = Field(None, description="Loan approval SMS detected in last 30 days.")
    loan_approval_sms_flag_c90_v2: Optional[bool] = Field(None, description="Loan approval SMS detected in last 90 days.")
    loan_approval_sms_flag_c180_v2: Optional[bool] = Field(None, description="Loan approval SMS detected in last 180 days.")
    loan_approval_sms_flag_c360_v2: Optional[bool] = Field(None, description="Loan approval SMS detected in last 360 days.")
    home_loan_emi_deduction_flag_c30: Optional[bool] = Field(None, description="Home loan EMI deduction detected in last 30 days.")
    home_loan_emi_deduction_flag_c90: Optional[bool] = Field(None, description="Home loan EMI deduction detected in last 90 days.")
    home_loan_emi_deduction_flag_c180: Optional[bool] = Field(None, description="Home loan EMI deduction detected in last 180 days.")
    home_loan_emi_deduction_flag_c360: Optional[bool] = Field(None, description="Home loan EMI deduction detected in last 360 days.")

    # ── Health insurance ──
    cnt_health_insurance_application_c30: Optional[int] = Field(None, description="Health insurance applications, last 30 days.")
    cnt_health_insurance_application_c90: Optional[int] = Field(None, description="Health insurance applications, last 90 days.")
    cnt_health_insurance_application_c180: Optional[int] = Field(None, description="Health insurance applications, last 180 days.")
    cnt_health_insurance_application_c360: Optional[int] = Field(None, description="Health insurance applications, last 360 days.")
    cnt_health_insurance_expired_c30: Optional[int] = Field(None, description="Health insurance expired events, last 30 days.")
    cnt_health_insurance_expired_c90: Optional[int] = Field(None, description="Health insurance expired events, last 90 days.")
    cnt_health_insurance_expired_c180: Optional[int] = Field(None, description="Health insurance expired events, last 180 days.")
    cnt_health_insurance_expired_c360: Optional[int] = Field(None, description="Health insurance expired events, last 360 days.")
    cnt_health_insurance_renewal_c30: Optional[int] = Field(None, description="Health insurance renewals, last 30 days.")
    cnt_health_insurance_renewal_c90: Optional[int] = Field(None, description="Health insurance renewals, last 90 days.")
    cnt_health_insurance_renewal_c180: Optional[int] = Field(None, description="Health insurance renewals, last 180 days.")
    cnt_health_insurance_renewal_c360: Optional[int] = Field(None, description="Health insurance renewals, last 360 days.")
    health_insurance_application_flag_c30: Optional[bool] = Field(None, description="Health insurance application flag, last 30 days.")
    health_insurance_application_flag_c90: Optional[bool] = Field(None, description="Health insurance application flag, last 90 days.")
    health_insurance_application_flag_c180: Optional[bool] = Field(None, description="Health insurance application flag, last 180 days.")
    health_insurance_application_flag_c360: Optional[bool] = Field(None, description="Health insurance application flag, last 360 days.")
    health_insurance_expired_flag_c30: Optional[bool] = Field(None, description="Health insurance expired flag, last 30 days.")
    health_insurance_expired_flag_c90: Optional[bool] = Field(None, description="Health insurance expired flag, last 90 days.")
    health_insurance_expired_flag_c180: Optional[bool] = Field(None, description="Health insurance expired flag, last 180 days.")
    health_insurance_expired_flag_c360: Optional[bool] = Field(None, description="Health insurance expired flag, last 360 days.")
    health_insurance_renewal_flag_c30: Optional[bool] = Field(None, description="Health insurance renewal flag, last 30 days.")
    health_insurance_renewal_flag_c90: Optional[bool] = Field(None, description="Health insurance renewal flag, last 90 days.")
    health_insurance_renewal_flag_c180: Optional[bool] = Field(None, description="Health insurance renewal flag, last 180 days.")
    health_insurance_renewal_flag_c360: Optional[bool] = Field(None, description="Health insurance renewal flag, last 360 days.")

    # ── Life insurance ──
    cnt_life_insurance_application_c30: Optional[int] = Field(None, description="Life insurance applications, last 30 days.")
    cnt_life_insurance_application_c90: Optional[int] = Field(None, description="Life insurance applications, last 90 days.")
    cnt_life_insurance_application_c180: Optional[int] = Field(None, description="Life insurance applications, last 180 days.")
    cnt_life_insurance_application_c360: Optional[int] = Field(None, description="Life insurance applications, last 360 days.")
    cnt_life_insurance_expired_c360: Optional[int] = Field(None, description="Life insurance expired events, last 360 days.")
    cnt_life_insurance_renewal_c360: Optional[int] = Field(None, description="Life insurance renewals, last 360 days.")
    life_insurance_application_flag_c30: Optional[bool] = Field(None, description="Life insurance application flag, last 30 days.")
    life_insurance_application_flag_c90: Optional[bool] = Field(None, description="Life insurance application flag, last 90 days.")
    life_insurance_application_flag_c180: Optional[bool] = Field(None, description="Life insurance application flag, last 180 days.")
    life_insurance_application_flag_c360: Optional[bool] = Field(None, description="Life insurance application flag, last 360 days.")
    life_insurance_expired_flag_c360: Optional[bool] = Field(None, description="Life insurance expired flag, last 360 days.")
    life_insurance_renewal_flag_c360: Optional[bool] = Field(None, description="Life insurance renewal flag, last 360 days.")

    # ── Tax features ──
    amt_adv_tax_y0_q1: Optional[float] = Field(None, description="Advance tax year-0 Q1 amount.")
    amt_adv_tax_y0_q2: Optional[float] = Field(None, description="Advance tax year-0 Q2 amount.")
    amt_adv_tax_y0_q3: Optional[float] = Field(None, description="Advance tax year-0 Q3 amount.")
    amt_adv_tax_y0_q4: Optional[float] = Field(None, description="Advance tax year-0 Q4 amount.")
    amt_adv_tax_y1_q1: Optional[float] = Field(None, description="Advance tax year-1 Q1 amount.")
    amt_adv_tax_y1_q2: Optional[float] = Field(None, description="Advance tax year-1 Q2 amount.")
    amt_adv_tax_y1_q3: Optional[float] = Field(None, description="Advance tax year-1 Q3 amount.")
    amt_adv_tax_y1_q4: Optional[float] = Field(None, description="Advance tax year-1 Q4 amount.")
    amt_tds_filed_y0: Optional[float] = Field(None, description="TDS amount filed, current year.")
    amt_tds_filed_y1: Optional[float] = Field(None, description="TDS amount filed, previous year.")
    avg_monthly_tds_y0: Optional[float] = Field(None, description="Average monthly TDS, current year.")
    avg_monthly_tds_y1: Optional[float] = Field(None, description="Average monthly TDS, previous year.")
    tds_time: Optional[str] = Field(None, description="Timestamp of latest TDS data.")
    itr_filed_flag_y0: Optional[bool] = Field(None, description="ITR filed in current financial year.")
    itr_filed_flag_y1: Optional[bool] = Field(None, description="ITR filed in previous financial year.")
    amt_gst_filed_y0: Optional[float] = Field(None, description="GST amount filed, current year.")
    amt_gst_filed_y1: Optional[float] = Field(None, description="GST amount filed, previous year.")
    gst_filed_flag_y0: Optional[bool] = Field(None, description="GST filed in current year.")
    gst_filed_flag_y1: Optional[bool] = Field(None, description="GST filed in previous year.")
    gst_bill_not_filed_c7_flag: Optional[bool] = Field(None, description="GST bill not filed in last 7 days flag.")
    gst_bill_not_filed_c30_flag: Optional[bool] = Field(None, description="GST bill not filed in last 30 days flag.")
    gst_bill_not_filed_c180_flag: Optional[bool] = Field(None, description="GST bill not filed in last 180 days flag.")
    num_gst_bill_not_filed_c7: Optional[int] = Field(None, description="Count of GST bills not filed, last 7 days.")
    num_gst_bill_not_filed_c30: Optional[int] = Field(None, description="Count of GST bills not filed, last 30 days.")
    num_gst_bill_not_filed_c180: Optional[int] = Field(None, description="Count of GST bills not filed, last 180 days.")
    gst_time: Optional[str] = Field(None, description="Timestamp of latest GST data.")

    # ── Tax-saving investments (ELSS, NPS, PPF) ──
    amt_elss_investment_c90: Optional[float] = Field(None, description="ELSS investment amount, last 90 days.")
    amt_elss_investment_c180: Optional[float] = Field(None, description="ELSS investment amount, last 180 days.")
    amt_elss_investment_c360: Optional[float] = Field(None, description="ELSS investment amount, last 360 days.")
    amt_nps_investment_c90: Optional[float] = Field(None, description="NPS investment amount, last 90 days.")
    amt_nps_investment_c180: Optional[float] = Field(None, description="NPS investment amount, last 180 days.")
    amt_nps_investment_c360: Optional[float] = Field(None, description="NPS investment amount, last 360 days.")
    cnt_nps_trx: Optional[int] = Field(None, description="Total NPS transaction count.")
    nps_flag: Optional[bool] = Field(None, description="NPS investment detected.")
    nps_trx_recency: Optional[int] = Field(None, description="Recency of latest NPS transaction.")
    investment_balance_nps_latest: Optional[float] = Field(None, description="Latest NPS investment balance.")
    amt_ppf_investment_c90: Optional[float] = Field(None, description="PPF investment amount, last 90 days.")
    amt_ppf_investment_c180: Optional[float] = Field(None, description="PPF investment amount, last 180 days.")
    amt_ppf_investment_c360: Optional[float] = Field(None, description="PPF investment amount, last 360 days.")
    cnt_ppf_trx: Optional[int] = Field(None, description="Total PPF transaction count.")
    ppf_flag: Optional[bool] = Field(None, description="PPF investment detected.")
    ppf_trx_recency: Optional[int] = Field(None, description="Recency of latest PPF transaction.")
    investment_balance_ppf_latest: Optional[float] = Field(None, description="Latest PPF investment balance.")

    # ── EPF features ──
    epf_flag: Optional[bool] = Field(None, description="EPF contributions detected.")
    epf_claim_recency: Optional[int] = Field(None, description="Recency of latest EPF claim.")
    epf_credit_avg_3mo: Optional[float] = Field(None, description="Average EPF credit over 3 months.")
    epf_credit_avg_6mo: Optional[float] = Field(None, description="Average EPF credit over 6 months.")
    epf_credit_latest_6mo: Optional[float] = Field(None, description="Total EPF credit in latest 6 months.")
    epf_latest_balance: Optional[float] = Field(None, description="Latest EPF balance.")
    epf_latest_balance_date: Optional[str] = Field(None, description="Date of latest EPF balance.")
    epf_latest_claim_amt: Optional[float] = Field(None, description="Latest EPF claim amount.")
    epf_vintage: Optional[int] = Field(None, description="EPF account vintage.")
    epf_time: Optional[str] = Field(None, description="Timestamp of latest EPF data.")

    # ── Wealth: Mutual Funds ──
    amt_mf_portfolio: Optional[float] = Field(None, description="Total MF portfolio value.")
    cnt_mf_trx: Optional[int] = Field(None, description="Total MF transaction count.")
    mf_flag: Optional[bool] = Field(None, description="MF investment detected.")
    mf_trx_recency: Optional[int] = Field(None, description="Recency of latest MF transaction.")
    investment_amt_mf: Optional[float] = Field(None, description="Total MF investment amount.")
    investment_amt_mf_latest: Optional[float] = Field(None, description="Latest MF investment amount.")
    investment_balance_mf_latest: Optional[float] = Field(None, description="Latest MF balance.")

    # ── Wealth: Fixed Deposits ──
    cnt_fd_accounts: Optional[int] = Field(None, description="Total FD account count.")
    cnt_fd_trx: Optional[int] = Field(None, description="Total FD transaction count.")
    fd_flag: Optional[bool] = Field(None, description="FD investment detected.")
    fd_trx_recency: Optional[int] = Field(None, description="Recency of latest FD transaction.")
    investment_amt_fd: Optional[float] = Field(None, description="Total FD investment amount.")
    investment_balance_fd_latest: Optional[float] = Field(None, description="Latest FD balance.")

    # ── Wealth: SIP ──
    sip_flag: Optional[bool] = Field(None, description="SIP investment detected.")
    sip_trx_recency: Optional[int] = Field(None, description="Recency of latest SIP transaction.")
    cnt_sip_trx: Optional[int] = Field(None, description="Total SIP transaction count.")
    investment_amt_sip: Optional[float] = Field(None, description="Total SIP investment amount.")
    investment_balance_sip_latest: Optional[float] = Field(None, description="Latest SIP balance.")

    # ── Wealth: Recurring Deposits ──
    rd_flag: Optional[bool] = Field(None, description="RD investment detected.")
    rd_trx_recency: Optional[int] = Field(None, description="Recency of latest RD transaction.")
    cnt_rd_trx: Optional[int] = Field(None, description="Total RD transaction count.")
    amt_rd_accounts_c180: Optional[float] = Field(None, description="RD account amounts, last 180 days.")
    investment_amt_rd: Optional[float] = Field(None, description="Total RD investment amount.")
    investment_balance_rd_latest: Optional[float] = Field(None, description="Latest RD balance.")

    # ── Wealth: Maturity ──
    cnt_fd_rd_mf_maturity_c30: Optional[int] = Field(None, description="FD/RD/MF maturity count, last 30 days.")
    cnt_fd_rd_mf_maturity_c60: Optional[int] = Field(None, description="FD/RD/MF maturity count, last 60 days.")
    cnt_fd_rd_mf_maturity_c90: Optional[int] = Field(None, description="FD/RD/MF maturity count, last 90 days.")
    cnt_fd_rd_mf_maturity_c180: Optional[int] = Field(None, description="FD/RD/MF maturity count, last 180 days.")
    cnt_fd_rd_mf_maturity_c360: Optional[int] = Field(None, description="FD/RD/MF maturity count, last 360 days.")


# ── Feature blocks ───────────────────────────────────────────────────────────

class Features(BaseModel):
    """Feature data supplied alongside the insight request (e.g. Finbox signals)."""

    finbox: Optional[InsightFinboxFeatures] = Field(
        default=None,
        description="Finbox feature set. All fields are optional; unknown keys are accepted.",
    )

    model_config = ConfigDict(populate_by_name=True)


# ── Request / response ───────────────────────────────────────────────────────

class InsightInputRequest(BaseModel):
    """Request body for `POST /v1/ffr_insight`.

    Contains the request metadata, financial data payload, and optional
    external features used to generate per-pillar insight cards.
    """

    model_config = ConfigDict(extra="ignore")

    metadata: FfrRequestMetadata = Field(description="Request envelope with correlation IDs and pillar selection.")
    data: FfrScreenData = Field(description="Structured financial data payload.")
    features: Features = Field(description="External feature blocks (e.g. Finbox).")

    @model_validator(mode="after")
    def check_pillar_fields(self) -> InsightInputRequest:
        validate_pillar_fields(self.metadata.type, self.data)
        return self


class InsightErrorBody(BaseModel):
    """Error envelope returned when insight generation fails."""

    code: str = Field(description="Machine-readable error code, e.g. `VALIDATION_ERROR`.")
    message: str = Field(description="Human-readable error summary.")
    details: List[ValidationDetail] = Field(
        default_factory=list,
        description="Per-field validation failure details (empty on non-validation errors).",
    )


class InsightItem(BaseModel):
    """A single LLM-generated insight card."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "spending_high_ratio",
                    "theme": "Overspending",
                    "headline": "Your spend-to-income ratio is above 70%",
                    "description": "Consider reviewing discretionary expenses to improve your savings buffer.",
                    "cta": {"text": "View Spending", "action": "jio://cashflow/view"},
                }
            ]
        }
    )

    id: str = Field(description="Unique insight identifier.")
    theme: str = Field(description="Thematic tag, e.g. `Overspending`, `Debt Risk`.")
    headline: str = Field(description="Short, attention-grabbing headline.")
    description: str = Field(description="Detailed explanation of the insight.")
    cta: CTAObject = Field(description="Call-to-action for this insight.")


class InsightGroups(BaseModel):
    """Insight cards grouped by pillar, with an optional cross-pillar top insight."""

    top_insight: Optional[InsightItem] = Field(
        default=None,
        description="Single most important cross-pillar insight (may be null).",
    )
    spending: List[InsightItem] = Field(default_factory=list, description="Spending pillar insight cards.")
    borrowing: List[InsightItem] = Field(default_factory=list, description="Borrowing pillar insight cards.")
    protection: List[InsightItem] = Field(default_factory=list, description="Protection pillar insight cards.")
    wealth: List[InsightItem] = Field(default_factory=list, description="Wealth pillar insight cards.")
    tax: List[InsightItem] = Field(default_factory=list, description="Tax pillar insight cards.")


class InsightResponseMetadata(BaseModel):
    """Metadata envelope for insight responses."""

    customer_id: str = Field(description="Echo of the input customer_id.")
    request_id: str = Field(description="Echo of the input request_id.")
    timestamp: str = Field(description="ISO-8601 response generation timestamp.")
    version: str = Field(description="API version string.")


class InsightOutputResponse(BaseModel):
    """Response body for `POST /v1/ffr_insight`.

    On success, `data` contains the grouped insight cards and `error` is null.
    On failure, `error` contains the error details and `data` is null.
    """

    metadata: InsightResponseMetadata = Field(description="Response metadata (customer_id, request_id, timestamp, version).")
    error: Optional[InsightErrorBody] = Field(
        default=None,
        description="Error details; null on success.",
    )
    data: Optional[InsightGroups] = Field(
        default=None,
        description="Grouped insight cards; null on error.",
    )
