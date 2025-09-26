import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import math
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
from twilio.rest import Client
import os

# ---------------- Loan payoff calculations ---------------- #
def calculate_payoff(balance, rate, monthly_payment):
    """Return months to payoff with interest (compound monthly)."""
    months = 0
    total_interest = 0
    while balance > 0 and months < 600:
        interest = balance * (rate / 100 / 12)
        balance += interest
        balance -= monthly_payment
        if balance < 0: balance = 0
        total_interest += interest
        months += 1
    return months, total_interest

def snowball(loans, extra):
    loans = sorted(loans, key=lambda x: x["balance"])
    return simulate(loans, extra)

def avalanche(loans, extra):
    loans = sorted(loans, key=lambda x: x["rate"], reverse=True)
    return simulate(loans, extra)

def simulate(loans, extra):
    loans = [loan.copy() for loan in loans]
    months = 0
    total_interest = 0
    while any(l["balance"] > 0 for l in loans) and months < 600:
        extra_left = extra
        for loan in loans:
            if loan["balance"] <= 0:
                continue
            interest = loan["balance"] * (loan["rate"] / 100 / 12)
            loan["balance"] += interest
            total_interest += interest
            pay = min(loan["min_payment"], loan["balance"])
            loan["balance"] -= pay
            extra_left -= pay
        extra_left = max(0, extra_left)
        if extra_left > 0:
            target_loan = loans[0] if loans[0]["balance"] > 0 else next((l for l in loans if l["balance"] > 0), None)
            if target_loan:
                pay = min(extra_left, target_loan["balance"])
                target_loan["balance"] -= pay
        months += 1
    return months, total_interest

# ---------------- PDF generator ---------------- #
def generate_pdf(salary, savings, debt_plan, advice, loans, expenses):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setFont("Helvetica", 12)
    c.drawString(50, 750, f"Budget Report - Salary {salary:,.0f} KES")
    c.drawString(50, 730, f"Savings this month: {savings:,.0f} KES")
    c.drawString(50, 710, f"Expenses: {sum(expenses.values()):,.0f} KES")

    y = 690
    c.drawString(50, y, "Loans:")
    y -= 20
    for loan in loans:
        c.drawString(60, y, f"{loan['name']}: Balance {loan['balance']:,.0f} KES, Rate {loan['rate']:.1f}%, Min {loan['min_payment']:,.0f} KES")
        y -= 20

    c.drawString(50, y-20, "Debt payoff simulation:")
    y -= 40
    for method, (months, interest) in debt_plan.items():
        c.drawString(60, y, f"{method}: {months} months, Interest = {interest:,.0f} KES")
        y -= 20

    c.drawString(50, y-20, "Expenses:")
    y -= 40
    for label, amount in expenses.items():
        c.drawString(60, y, f"{label}: {amount:,.0f} KES")
        y -= 20

    c.drawString(50, y-20, "Advice:")
    text = c.beginText(60, y-40)
    for line in advice.split("\n"):
        text.textLine(line)
    c.drawText(text)
    c.save()
    pdf = buffer.getvalue()
    buffer.close()
    return pdf

# ---------------- Streamlit UI ---------------- #
st.set_page_config(page_title="Budget & Debt Coach", layout="wide")
st.title("💰 Budget & Debt Coach (Interest-aware)")

# Authentication
with open("D:/overcoming debts/config.yaml", "r") as file:
    config = yaml.load(file, Loader=SafeLoader)
authenticator = stauth.Authenticate(config['credentials'], config['cookie']['name'], config['cookie']['key'], config['cookie']['expiry_days'])
name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status:
    if f'history_{username}' not in st.session_state:
        st.session_state[f'history_{username}'] = []
    if 'current_savings' not in st.session_state:
        st.session_state.current_savings = 0.0

    with st.sidebar:
        st.header("Budget Settings")
        salary = st.number_input("Monthly Salary (KES)", min_value=0, step=1000)
        use_fixed_savings = st.checkbox("Use fixed savings amount", value=True)
        if use_fixed_savings:
            savings = st.number_input("Fixed monthly savings (KES)", min_value=0.0, step=100.0, value=4000.0)
            debt_budget = salary * 0.2
            expenses_budget = salary - savings - debt_budget
        else:
            default_split = st.slider("Savings/Debt/Expenses (%)", 0, 100, (10, 20, 70))
            savings = salary * (default_split[0] / 100.0)
            debt_budget = salary * (default_split[1] / 100.0)
            expenses_budget = salary * (default_split[2] / 100.0)
        emergency_fund_target = st.number_input("Emergency Fund Target (KES)", min_value=0.0, step=100.0)

    st.header("Loans")
    num_loans = st.number_input("Number of loans", min_value=0, step=1)
    loans = []
    for i in range(int(num_loans)):
        st.subheader(f"Loan {i+1}")
        name = st.text_input(f"Loan {i+1} Name", key=f"name{i}")
        balance = st.number_input(f"Balance (KES)", min_value=0, step=500, key=f"bal{i}")
        rate = st.number_input(f"Interest rate (%)", min_value=0.0, step=0.1, key=f"rate{i}")
        min_payment = st.number_input(f"Minimum monthly payment (KES)", min_value=0, step=500, key=f"min{i}")
        loans.append({"name": name, "balance": balance, "rate": rate, "min_payment": min_payment})

    st.header("Expenses")
    num_expenses = st.number_input("Number of expense categories", min_value=0, step=1)
    expenses = {}
    for i in range(int(num_expenses)):
        label = st.text_input(f"Expense {i+1} name", key=f"exp{i}")
        amount = st.number_input(f"{label} (KES)", min_value=0, step=500, key=f"amt{i}")
        if label:
            expenses[label] = amount

    user_phone = st.text_input("Phone Number for Reminders (+254...)", key="phone")

    if st.button("Calculate & Generate Interest-aware Plan"):
        # Validation
        if salary <= 0:
            st.error("Salary must be positive.")
            st.stop()
        for i, loan in enumerate(loans):
            if not loan["name"]:
                st.error(f"Loan {i+1} name cannot be empty.")
                st.stop()
            if loan["balance"] < 0 or loan["rate"] < 0 or loan["min_payment"] < 0:
                st.error(f"Loan {i+1}: Balance, rate, and minimum payment must be non-negative.")
                st.stop()
        total_min_payments = sum(loan["min_payment"] for loan in loans)
        if total_min_payments > debt_budget:
            st.error(f"Total minimum payments ({total_min_payments:,.0f} KES) exceed debt budget ({debt_budget:,.0f} KES).")
            st.stop()
        total_expenses = sum(expenses.values())
        if total_expenses > expenses_budget:
            st.warning(f"Expenses ({total_expenses:,.0f} KES) exceed budget ({expenses_budget:,.0f} KES).")
        else:
            st.success(f"Expenses within budget. Spare: {expenses_budget - total_expenses:,.0f} KES.")

        # Calculations
        snow_months, snow_interest = snowball(loans, debt_budget)
        ava_months, ava_interest = avalanche(loans, debt_budget)
        debt_plan = {"Snowball": (snow_months, snow_interest), "Avalanche": (ava_months, ava_interest)}
        st.session_state.current_savings += savings

        st.subheader("Debt Payoff Comparison")
        st.write(f"**Snowball:** {snow_months} months, interest {snow_interest:,.0f} KES")
        st.write(f"**Avalanche:** {ava_months} months, interest {ava_interest:,.0f} KES")

        advice = "Avalanche saves more money in interest.\nStick to avalanche if discipline is high." if ava_interest < snow_interest else "Snowball gives faster wins.\nUse snowball for motivation."
        st.subheader("Advice")
        st.write(advice.replace("\n", "  \n"))

        # History
        history_entry = {
            "month": pd.Timestamp.now().strftime("%Y-%m"),
            "salary": salary,
            "savings": savings,
            "debt_budget": debt_budget,
            "expenses_budget": expenses_budget,
            "total_expenses": total_expenses,
            "snowball_months": snow_months,
            "snowball_interest": snow_interest,
            "avalanche_months": ava_months,
            "avalanche_interest": ava_interest
        }
        st.session_state[f'history_{username}'].append(history_entry)
        pd.DataFrame(st.session_state[f'history_{username}']).to_csv("D:/overcoming debts/budget_history.csv", index=False)

        # Chart
        labels = ["Savings", "Debt", "Expenses"]
        values = [savings, debt_budget, expenses_budget]
        fig, ax = plt.subplots()
        ax.pie(values, labels=labels, autopct='%1.1f%%')
        st.pyplot(fig)

        # PDF
        pdf = generate_pdf(salary, savings, debt_plan, advice, loans, expenses)
        st.download_button("Download PDF Report", pdf, file_name="budget_report.pdf", mime="application/pdf")

        # Reminders
        if user_phone and st.button("Send Payment Reminders"):
            client = Client(os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN"))
            message_body = "Budget & Debt Coach Reminders:\n"
            for loan in sorted(loans, key=lambda x: x["rate"], reverse=True):
                message_body += f"Pay {loan['min_payment']:,.0f} KES to {loan['name']}.\n"
            message = client.messages.create(body=message_body, from_=os.getenv("TWILIO_NUMBER"), to=user_phone)
            st.success(f"Reminder sent to {user_phone}")

    st.subheader("History")
    if st.session_state[f'history_{username}']:
        st.dataframe(pd.DataFrame(st.session_state[f'history_{username}']))
        st.download_button("Download History (CSV)", pd.DataFrame(st.session_state[f'history_{username}']).to_csv(index=False), "budget_history.csv", "text/csv")
else:
    st.error("Please log in to continue.")
    st.stop()