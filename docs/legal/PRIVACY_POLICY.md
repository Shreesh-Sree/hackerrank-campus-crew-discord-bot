# Privacy Policy — HackerRank Campus Crew Discord Bot (`hrcc_bot`)

**Effective Date:** September 19, 2026  
**Last Updated:** September 19, 2026  
**Application Name:** HackerRank Campus Crew Bot (`@hackerrank_campus_crew_bot`)  
**Developer & Maintainer:** Sreesanth R (`shreesh.exe22@gmail.com`)  
**Official Program:** HackerRank Campus Crew Ambassador Program (`handbook.hackerrankcampuscrew.xyz`)

---

## 1. Introduction & Scope
This Privacy Policy outlines how the **HackerRank Campus Crew Discord Bot** ("Bot", "Service", "we", "us") collects, uses, stores, and protects personal data and user information when you interact with the Bot on Discord (via direct messages, server mentions, or slash commands).

By using the Bot or inviting it to your Discord server, you consent to the data practices described in this policy.

---

## 2. Information We Collect

### A. Information Provided Directly by Users
- **Discord Account Information:** Discord User ID (`Snowflake`), Username, Global Display Name, and Server/Guild ID.
- **Support Messages & Queries:** Message text sent directly to the Bot via direct mentions (`@hrcc_bot`) or direct messages (DMs) related to campus events, platform support, and escalations.
- **Event & Contest Metadata:** Event name, event date, college/institution name, participant counts, and contest URLs provided when configuring events or creating support tickets.
- **Contest Result Files (Optional):** Spreadsheet files (`.csv` or `.xlsx`) uploaded by campus ambassadors for winner validation, Canva certificate generation, and reward verification.

### B. Information We Do NOT Collect
- We **do not** collect personal passwords, billing credentials, credit card numbers, or government IDs.
- We **do not** read, log, or store casual messages in public channels that are dismissed by our noise gate (`NO_REPLY`).

---

## 3. How We Use Your Information
We use the collected information strictly to provide operational campus event support, specifically to:
1. **Answer Ambassador Queries:** Retrieve relevant SOPs, guidelines, and rules from the official Ambassador Handbook via our grounded AI inference engine.
2. **Facilitate Escalation Tickets:** Dispatch structured support tickets to designated program leads (**Sanskruti** for Operations/Rewards, **Sreesanth** for Technical/HRW, **Nitish** for Design/Brand) and deliver their direct responses back to ambassadors.
3. **Validate Event Results & Rewards:** Process contest CSVs to count active participants (`score > 0`), determine eligibility for the 1-Year HackerRank Infinity Plan or physical merchandise (`≥ 300` participants), and format data for Canva bulk certificate creation.
4. **Proactive Event Lifecycle Reminders:** Send automated reminders (T-72h, T-24h, T+24h) regarding contest preparation, buffer windows, and CSV exports.

---

## 4. Data Storage, Security & Retention

- **Database Storage:** Operational data (escalation tickets, ambassador event records, conversation turns) is stored in a secure, self-hosted database (PostgreSQL / SQLite with Write-Ahead Logging).
- **Inference Security:** Message queries processed through our AI engine run on a private, self-hosted infrastructure (`ai-server`) and are **never** shared with third-party public AI providers for model training.
- **Secret & Token Scrubbing:** The Bot employs automated regex filters to redact API keys, tokens, and credentials from all logs and responses.
- **Retention Period:**
  - Active conversation context is retained for the duration of the support thread.
  - Event records and escalation ticket histories are retained for up to twelve (12) months for reward auditability and compliance, after which they are permanently archived or deleted.

---

## 5. Third-Party Sharing & Disclosure
We do **not** sell, rent, monetize, or trade your personal information. Data is shared exclusively under the following strict conditions:
- **HackerRank Campus Crew Leadership:** Ticket descriptions, winner lists, and college names are shared with verified HackerRank Campus Crew program staff solely to dispatch physical merchandise, activate software licenses, and issue certificates.
- **Legal Requirements:** We may disclose information only if required by applicable law, regulation, or legal process.

---

## 6. Your Rights & Data Deletion
Under applicable data protection laws (including GDPR and CCPA principles), you have the right to:
1. **Access:** Request a copy of the event records or tickets associated with your Discord User ID.
2. **Rectification:** Request correction of inaccurate event records or college affiliations.
3. **Deletion (Right to be Forgotten):** Request the deletion of your user data, conversation turns, and event records from our database.

To request data access or deletion, use the `/my_status` command or email **Sreesanth R** directly at:  
📧 **`shreesh.exe22@gmail.com`**  
*(Please include your Discord Username and 18-digit User ID for verification).*

---

## 7. Changes to This Privacy Policy
We reserve the right to update this Privacy Policy as our features evolve. Any changes will be posted in this repository and announced in the official HackerRank Campus Crew Discord server.

---

## 8. Contact Us
For any privacy questions, security concerns, or data requests, please contact:
- **Lead Developer:** Sreesanth R
- **Email:** `shreesh.exe22@gmail.com`
- **Program Handbook:** [handbook.hackerrankcampuscrew.xyz](https://handbook.hackerrankcampuscrew.xyz)
