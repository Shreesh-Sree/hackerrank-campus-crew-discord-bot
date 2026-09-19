# HackerRank Campus Crew — Official Handbook Reference

> **Core Knowledge Base for the HackerRank Campus Crew Support Bot**  
> Source Reference: Official Ambassador Handbook (`handbook.hackerrankcampuscrew.xyz`)

---

## 1. Program Mission & Ambassador Identity

The **HackerRank Campus Crew** is a selective 6-month volunteer student ambassador program designed to:
- Empower campus developer communities.
- Bridge the practical divide between university academics and enterprise industry technical hiring.
- Promote hands-on problem solving, algorithmic thinking, and modern software skills through the HackerRank ecosystem.

### Key Ambassador Responsibilities
1. Host at least **one HackerRank-platform event every month** (coding contest, hackathon, workshop, or technical seminar).
2. Maintain high contest integrity (active proctoring, testcase verification, plagiarism checks).
3. Submit post-event reports, winner rosters, and participation lists within **1–2 business days**.
4. Act as the primary liaison (SPOC) between university students, faculty, and the HackerRank community team.

---

## 2. Platform Architecture & Triad Rules

Ambassadors interact with three distinct portals. Confusing these platforms is the single most common operational error:

```
                          ┌───────────────────────────┐
                          │   HACKERRANK ECOSYSTEM    │
                          └─────────────┬─────────────┘
                                        │
           ┌────────────────────────────┼────────────────────────────┐
           ▼                            ▼                            ▼
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│  HackerRank for Work │     │ HackerRank Community │     │  HackerRank SkillUp  │
│        (HRW)         │     │        (HRC)         │     │                      │
├──────────────────────┤     ├──────────────────────┤     ├──────────────────────┤
│ hackerrank.com/work  │     │    hackerrank.com    │     │ hackerrank.com/skillup│
├──────────────────────┤     ├──────────────────────┤     ├──────────────────────┤
│ • Official enterprise│     │ • Public/private     │     │ • Self-paced student │
│   assessment portal  │     │   contest creator    │     │   learning modules   │
│ • Custom testcases,  │     │ • Primary fallback   │     │ • Industry certs     │
│   proctoring reports │     │   if HRW is pending  │     │ • NOT FOR LIVE       │
│ • NO CHAKRA TAB!     │     │ • Massive concurrency│     │   CAMPUS EVENTS      │
└──────────────────────┘     └──────────────────────┘     └──────────────────────┘
```

### 1. HackerRank for Work (HRW)
- **URL:** `hackerrank.com/work/login`
- **Role:** Enterprise-grade recruitment and assessment environment provided to ambassadors.
- **Capabilities:** Automated scoring, runtime environment isolation, testcase weighting, plagiarism detection, proctoring snapshots.
- **Critical Policy (The Chakra Rule):**
  > [!CAUTION]
  > **THE `Chakra` TAB INSIDE HRW IS STRICTLY INTERNAL TO HACKERRANK STAFF.**  
  > Ambassadors are strictly forbidden from accessing or triggering tests via Chakra. Accessing Chakra can trigger security audits and revoke ambassador access. If mock interviews are required, ambassadors must request mock interview vouchers from the Program Manager.

### 2. HackerRank Community (HRC)
- **URL:** `hackerrank.com`
- **Role:** Public developer portal with built-in community contest builder (`hackerrank.com/administration/contests/create`).
- **Use Cases:**
  - Used immediately as an operational fallback if HRW account activation is pending.
  - Used for large open-entry contests with massive concurrent participation across multiple colleges.

### 3. HackerRank SkillUp
- **URL:** `hackerrank.com/skillup`
- **Role:** Self-paced developer certification courses (Problem Solving, Python, SQL, REST APIs, etc.).
- **Rule:** For individual student learning only. **Never host a live campus event or contest on SkillUp.**

---

## 3. Event Standard Operating Procedures (SOPs)

### Coding Contests
1. **Timing Buffer:** Contests that hit their scheduled end timestamp **cannot be reopened** under any circumstance. Always configure a **15–30 minute buffer** to accommodate late network submissions.
2. **Problem Setting:** Use curated problems with hidden testcases to prevent hardcoded outputs (`if n == 1: print(2)`).
3. **Plagiarism Checking:** Utilize HRW's automated code similarity checker. Flagged submissions must be manually reviewed before announcing final rankings.

### Workshops & Tech Talks
1. **Speaker Requests:** Official HackerRank engineer speaker or judge requests must be submitted at least **2 weeks in advance** to Program Manager (`Sanskruti`).
2. **Platform Demo:** Incorporate a live coding session demonstrating how industry recruiters assess candidate code on HackerRank.

---

## 4. Reward Tiers & Activation Workflow

### Official Reward Matrix

| Tier | Active Participant Count | Winner Package | Merch Delivery | Certificates |
| :---: | :---: | :--- | :---: | :---: |
| **Tier 1** | **< 300 Participants** | • 1-Year HackerRank Infinity Plan<br>• Mock Interview Credits<br>• 6-Month Access to 1,500+ AI Tools | ❌ No physical merch | ✅ Official Certificate |
| **Tier 2** | **≥ 300 Participants** | • 1-Year HackerRank Infinity Plan<br>• Mock Interview Credits<br>• 6-Month Access to 1,500+ AI Tools<br>• **Official HackerRank Merchandise Pack** | ✅ Shipped to Ambassador SPOC | ✅ Official Certificate |

### The "Active Participant" Standard
- **Eligible:** An attendee who registers, signs into the contest, and **executes/submits code or test answers** for at least one challenge.
- **Ineligible:** An attendee who registers on the event landing page but does not submit any code on the HackerRank platform.

### Winner Reward Activation Steps
1. Within **24–48 hours** of contest completion, compile the winners' data in a spreadsheet:
   - Full Name
   - College / University
   - Contest Rank & Score
   - **Exact HackerRank Registered Email** (must match their login email on hackerrank.com)
2. Submit the spreadsheet via Direct Message to Program Manager (`Sanskruti`).
3. Rewards will be directly provisioned to the recipients' HackerRank accounts.

---

## 5. Participation Certificates Automation

All active participants are entitled to official HackerRank Campus Crew participation certificates.

### Bulk Generation Pipeline (Canva Bulk Create)
1. **Obtain Approved Template:** Contact Design Lead (`Nitish`) for the official HackerRank Campus Crew vector frame.
2. **Export Platform CSV:** Export the participant submission roster from HRW/HRC.
3. **Format Data:** Format columns matching the standard schema:
   ```csv
   Full Name,Email Address,College Name,Event Name,Date,Rank,Score
   Siddharth Verma,siddharth@example.edu,National Institute of Technology,Campus Code Wars,2026-09-19,1,300
   Pooja Sharma,pooja@example.edu,National Institute of Technology,Campus Code Wars,2026-09-19,2,285
   ```
4. **Connect in Canva:**
   - In Canva, select **Apps $\rightarrow$ Bulk Create $\rightarrow$ Upload CSV**.
   - Right-click text elements on the certificate template and select **Connect Data** for `Full Name`, `Event Name`, `Date`, etc.
   - Click **Generate Pages** to export individual high-resolution PDFs or PNGs.

---

## 6. Escalation & Lead Directory

When handling questions, always route members to the exact designated lead:

| Role | Lead Name | Direct Responsibilities |
| :--- | :--- | :--- |
| **Program Manager** | **Sanskruti** | • Winner rewards activation<br>• Welcome onboarding packages & kits<br>• Official HackerRank merchandise shipment tracking<br>• Speaker, mentor, and judge approvals<br>• Escalations regarding college permissions |
| **Technical Lead** | **Sreesanth** | • HRW enterprise recruiter account invitations<br>• Access troubleshooting & password resets<br>• Contest platform runtime bugs & compiler issues<br>• SkillUp platform questions |
| **Design Lead** | **Nitish** | • Official logo packs & high-res vectors<br>• Verified certificate Canva templates<br>• Social media poster templates & brand asset review |
