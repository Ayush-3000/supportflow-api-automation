# Portfolio showcase

## Project title

SupportFlow — Customer Support Automation with API Order Lookup and Human Approval

## Description

SupportFlow is a runnable portfolio project that turns support tickets into evidence-backed draft replies. It connects a ticket webhook to a read-only order API, checks the order against the customer's email, and retrieves approved policy content for common questions. A review dashboard lets an operator inspect sources, edit the reply, and explicitly approve delivery to a helpdesk API.

The workflow also demonstrates duplicate protection, bounded retries, failure queues, concurrent approval protection, delivery receipts and an audit history. Refunds, sensitive requests, identity mismatches and unsupported questions are escalated to a human. An optional OpenAI adapter adds structured AI drafting while preserving the approval requirement and a template fallback.

The project uses Python, FastAPI, HTTPX, SQLite and a lightweight browser dashboard, with an automated test suite and GitHub Actions. Demonstrations use fictional orders and a local helpdesk; live Shopify, helpdesk and OpenAI connections have not been verified. It is a portfolio prototype, not a past client deployment.

## Skills demonstrated

API integration · Webhooks · Python · FastAPI · GraphQL · Workflow automation · Human approval · Error handling · Automated testing · AI integration architecture

## 90-second walkthrough

| Time | On screen | What to explain |
| --- | --- | --- |
| 0–15 sec | Dashboard and demo notice | “This is a fictional support workflow. Every reply requires human review.” |
| 15–35 sec | Run Order status | “The workflow queries the order API and checks the order/customer match before drafting from fulfillment and tracking facts.” |
| 35–55 sec | Evidence and editable draft | “The reviewer sees the source, edits the wording, and controls delivery. The default uses templates; an optional AI adapter follows the same gate.” |
| 55–70 sec | Approve; show receipt and audit | “The reply goes to the local helpdesk only after approval, with a recorded reviewer label and provider receipt.” |
| 70–85 sec | Refund request and API outage | “Sensitive requests go to a person. Read failures use bounded retries and enter a recoverable queue.” |
| 85–90 sec | GitHub README and tests | “The repository includes the runnable demo, contracts, limitations and repeatable tests.” |

## Screenshots to use

- `screenshots/review-workspace.jpg`: dashboard with the verified evidence and draft.
- `screenshots/approved-reply.jpg`: reviewed reply with a receipt and activity history.

When discussing this project with clients, describe the parts you can demonstrate and explain. Do not present synthetic orders as client data or this prototype as a system already deployed for a business. The project does not establish previous production Shopify, LiveAgent or n8n experience.
