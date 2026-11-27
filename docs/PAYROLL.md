# Payroll

`services/payroll.py`

## Salary structure

Created from the annual CTC, either at onboarding (the opening's CTC) or by HR on the employee's **Payroll** tab.

| Component (monthly) | Rule |
|---|---|
| Basic | 40% of monthly CTC |
| HRA | 50% of Basic |
| Employer PF | 12% of Basic, on Basic capped at ₹15,000 (part of CTC, not paid out) |
| Special allowance | Monthly CTC − Basic − HRA − Employer PF |

HR can also set a **monthly TDS** amount per employee, based on the employee's tax regime and declarations.

Each change creates a new structure row with an `effective_from` date. History is kept, and payroll uses the structure in effect at the end of the month.

## Monthly payslip

**HR → Payroll → Generate payslips** for a month (`YYYY-MM`). Re-running a month recalculates it.

1. **Working days**: weekdays in the month (per `HRM_WORK_WEEK_DAYS`) minus company holidays.
2. **Eligible days**: working days from the joining date if the employee joined mid-month.
3. **Loss of pay**: approved *unpaid* leave days (LWP) in the month.
4. **Paid days** = eligible days − loss of pay.
5. **Earnings** = each component × paid days ÷ working days.
6. **Deductions**:
   - Employee PF: 12% of the earned Basic, capped at ₹15,000 Basic
   - Professional Tax: ₹200 when gross exceeds ₹15,000
   - TDS: the monthly amount HR set
7. **Net pay** = gross − deductions.

Employees get a notification. The payslip appears in their portal with a plain-language explanation of each line, and the HR assistant can explain it too.

## Deliberate limits

* **Income tax is not computed automatically.** It depends on the regime (old or new), declarations and other income. HR enters monthly TDS. A tax engine can replace this later without changing payslip generation.
* Professional tax uses one flat rule. Make it state-wise when Kairoz has employees in several states.
* No bank file export yet. The payslip table with totals is the input for the bank's bulk-upload format.
