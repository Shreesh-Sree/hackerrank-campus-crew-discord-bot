# Ambassador Operations & Self-Service Support Suite (`AMBASSADOR_OPERATIONS.md`)

> **Technical Specification for Ambassador Self-Service Workflows & Operational Assistants**  
> Target System: HackerRank Campus Crew Super Agent (`hrcc_bot`)

---

## 1. Interactive New Ambassador Onboarding Walkthrough (`/onboard`)

### The Problem
When newly selected Campus Crew ambassadors join the Discord server, they feel overwhelmed by documentation and ask the same initial setup questions repeatedly (e.g. *"Where do I log in?"*, *"When do I get my T-shirt?"*, *"How do I create tests?"*).

### The Automated Onboarding Pipeline
When an ambassador receives the `@Ambassador` role or triggers `/onboard`:
1. The bot dispatches a private **Interactive Welcome DM Card**:
   ```
   ┌─────────────────────────────────────────────────────────────┐
   │ 🚀 WELCOME TO HACKERRANK CAMPUS CREW!                       │
   ├─────────────────────────────────────────────────────────────┤
   │ Congratulations on your selection as a student ambassador!  │
   │ Let's get your campus developer ecosystem up and running.   │
   │                                                             │
   │ 📋 Onboarding Checklist:                                    │
   │ [1/4] 🔑 Set up your HackerRank for Work (HRW) Recruiter Login│
   │ [2/4] 📖 Review the 3 Golden Rules (Chakra tab, Buffer, SLA)│
   │ [3/4] 👥 Meet your leadership contacts (Sanskruti, Sreesanth)│
   │ [4/4] 🏆 Learn about Reward Tiers (<300 vs >=300 coders)   │
   ├─────────────────────────────────────────────────────────────┤
   │ [ 🔑 HRW Setup Guide ]  [ 📖 The 3 Golden Rules ]  [ ✅ Done ] │
   └─────────────────────────────────────────────────────────────┘
   ```
2. **Interactive Rule Quiz:** The ambassador clicks `[ 📖 The 3 Golden Rules ]`, which presents 3 quick interactive buttons reinforcing that:
   - Chakra is strictly internal.
   - Buffer time must always be added.
   - Winner emails must match registered HackerRank account emails.

---

## 2. Official Resource & Asset Dispenser (`/resources`)

### The Problem
Ambassadors frequently ask in chat: *"Where can I find the official HackerRank presentation slides?"*, *"Can someone send the logo PNG?"*, *"How do I draft an invitation email to students?"*.

### The `/resources` Command Hub
Ambassadors run `/resources` to receive an interactive Discord Select Menu categorized into verified assets:

| Resource Category | Provided Assets & Downloads |
| :--- | :--- |
| **🎨 Official Brand Assets** | • High-resolution vector logo pack (Light & Dark variants)<br>• Verified Canva certificate frame template (approved by Nitish)<br>• Official social media poster frames |
| **📊 Presentation Decks** | • Official HackerRank Campus Crew Workshop Slide Deck (`.pptx` / Google Slides)<br>• "Cracking the Technical Coding Interview" standard presentation |
| **✉️ Copy-Paste Templates** | • College Dean / HOD lab reservation formal email draft<br>• Student contest invitation broadcast template<br>• Post-event winner announcement template |
| **📖 Official Documentation** | • Direct link to Handbook: `handbook.hackerrankcampuscrew.xyz`<br>• HRW Recruiter Assessment Creation SOP |

---

## 3. College Permission & Institutional Letter Generator (`/request-letter`)

### The Problem
To reserve college computer labs or gain permission for on-campus coding contests, university administrations (Principals, Deans, HODs) demand a formal, signed **Institutional Invitation Letter** from HackerRank.

### The Automated Pipeline
1. Ambassador triggers `/request-letter`.
2. A native Discord Modal collects structured details:
   - Ambassador Full Name
   - University / College Name & Department
   - Head of Department (HOD) Name & Title
   - Proposed Contest Name & Date
   - Expected Number of Attendees
3. The bot compiles a standardized PDF request package and routes it directly to Program Manager **Sanskruti** via DM:
   ```
   [ Request Received ] ──► [ Modal Verification ] ──► [ Route to Sanskruti ] ──► [ Formal PDF Issued ]
   ```
4. Once reviewed by Sanskruti, the signed institutional authorization letter is delivered back to the ambassador.

---

## 4. HackerRank Engineer / Speaker Request Assistant (`/request-speaker`)

### The Problem
Ambassadors hosting major hackathons or tech seminars frequently request HackerRank engineers as keynote speakers or judges.  
**Handbook Rule:** Speaker requests must be submitted at least **2 weeks (14 days) in advance**.

### Automated Request Validation
Ambassadors execute `/request-speaker`:
1. **Lead-Time Guard:** If the requested event date is `< 14 days` away, the bot immediately warns:
   > *"⚠️ Handbook Policy: HackerRank engineer requests require at least 14 days advance notice to accommodate engineer schedules. Please select a date at least 2 weeks from today."*
2. **Structured Briefing:** If $\ge 14$ days, prompts for:
   - Event Topic (e.g. *System Design at Scale, Competitive Programming, Generative AI in Code*)
   - Mode (Virtual Zoom/Meet vs On-Campus)
   - Expected Student Turnout
3. Packages the briefing and routes it directly to **Sanskruti** with an interactive confirmation card.

---

## 5. Post-Event Compliance & Report Submission Wizard (`/submit-report`)

### The Problem
Post-event reporting is mandatory to maintain active ambassador status and unlock merchandise shipping. Ambassadors often forget key metrics or delay submissions past the 48-hour SLA.

### The Interactive Submission Wizard
48 hours post-contest, or via `/submit-report`:
1. **Modal Form Inputs:**
   - Platform Used (HRW vs HRC)
   - Total Registered Students
   - **Total Active Participants** (Submitted code/answers)
   - Attached Winner Spreadsheet (`.csv` / `.xlsx`)
   - Contest Link URL
2. **Automated Audit:**
   - Confirms active participant count aligns with reward tiers.
   - Formats the summary into an official compliance record.
   - Archives the event in the database, automatically updating the ambassador's `/my-status` to `COMPLETED`.

---

## 6. Button-Driven Interactive Troubleshooting Trees

When an ambassador encounters a problem, they can click visual buttons rather than typing:

```
┌─────────────────────────────────────────────────────────────┐
│ 🛠️ HACKERRANK SELF-SERVICE TROUBLESHOOTING                 │
├─────────────────────────────────────────────────────────────┤
│ Select the issue you are experiencing:                      │
│                                                             │
│ [ 🔑 HRW Account Activation Pending ]                       │
│ [ ⚠️ Contest Closed / Buffer Time Issue ]                   │
│ [ 🎁 Winner Reward Activation Delayed ]                     │
│ [ 🏫 College Name Not Listed in Dropdown ]                  │
│ [ 🚨 Live Platform Outage / Compiler Error ]                │
└─────────────────────────────────────────────────────────────┘
```

### Example Decision Tree: `[ 🔑 HRW Account Activation Pending ]`
```
[ Click: HRW Activation Pending ]
              │
              ├── Step 1: Did you check your spam/promotions folder for the recruiter invite?
              │     ├── [ Yes, still not found ]
              │     └── [ Found it! Problem solved ]
              │
              ├── Step 2: Is your event scheduled within the next 48 hours?
              │     ├── [ Yes, event is soon! ] ──► Suggests HRC (Community) fallback immediately
              │     │                              and offers 1-click escalation to Sreesanth.
              │     └── [ No, event is next week ]──► Informs user that HRW onboarding batches run
              │                                      weekly; logs ticket for next batch.
```

---

## 7. Lead Support Analytics & Performance Dashboard (`/admin-stats`)

Visible exclusively to authorized program leadership (**Sanskruti**, **Sreesanth**, **Nitish**):

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 HACKERRANK CAMPUS CREW SUPPORT TELEMETRY (SEPTEMBER 2026)│
├─────────────────────────────────────────────────────────────┤
│ 📥 Total Inbound Queries:       1,482                       │
│ 🤖 Resolved Autonomously (RAG): 1,298 (87.6%)               │
│ 🎫 Escalated Tickets:           184 (12.4%)                 │
│ 🚨 P0 Emergency Outages:        2                           │
│                                                             │
│ 📌 Common Issues Distribution:                              │
│ • HRW Recruiter Access / Setup: 42%                         │
│ • Winner Email & Prize Queries: 28%                         │
│ • Certificate Canva Formatting: 18%                         │
│ • Speaker / Letter Requests:    12%                         │
│                                                             │
│ ⏱️ Mean Time to Resolution (MTTR):                          │
│ • Autonomous Bot:               1.4 seconds                 │
│ • Escalated Lead DM Tickets:    3.2 hours                   │
└─────────────────────────────────────────────────────────────┘
```
