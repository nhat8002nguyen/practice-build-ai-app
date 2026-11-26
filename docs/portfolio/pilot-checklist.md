# SMB Pilot Onboarding Checklist

This guide prepares a 1 to 2 week unpaid pilot with the first external small or medium business user after VPS deployment.
It covers what to collect, how to set expectations on privacy, how to reach out, which seed questions to verify first, and how to measure whether the pilot succeeded.

## 1. Documents needed from the partner

Ask the partner for 3 to 8 current support documents rather than an entire company drive.
The API accepts Markdown (`.md`) and text-selectable PDF (`.pdf`) uploads up to 10 MB per file, plus public HTTP or HTTPS FAQ pages via the URL crawler.

Request these document types first:

- **Refund, return, cancellation, or rescheduling policy:** exact day windows, eligibility rules, fees, and payout timelines.
- **Pricing, plans, or service catalog:** tier names, prices, included limits or seats, and billing cycle rules.
- **Shipping, delivery, or booking turnaround rules:** dispatch times, service areas, express options, or intake prerequisites.
- **Top 10 to 20 customer FAQs or saved macros:** canned email or chat replies that staff already paste every week.
- **Troubleshooting, setup, or care instructions:** step-by-step fixes customers can try before escalating.
- **Warranty, exclusions, and escalation rules:** what is not covered and when a request must go to a human manager.

Ask the partner **not** to send:

- Customer exports containing names, emails, phone numbers, addresses, order histories, or health and payment records.
- Scanned image-only PDFs without selectable text, because the PDF parser reads embedded text rather than running OCR.
- API keys, staff passwords, or unpublished legal agreements.
- Conflicting draft versions of the same policy, because outdated rules will compete with current ones during retrieval.

## 2. Privacy and safety note (share with partner)

Send or read this note before the partner shares any internal files:

> **How your data is handled during this pilot**
>
> - **Scope:** Please share only general support policies, product or service guides, and FAQs.
>   Do not include customer personal data (names, emails, phone numbers, order records, or payment details) or internal credentials.
> - **Isolation:** Your documents live under a dedicated account on a private server.
>   Every database query and vector search is filtered to your account ID so workspaces do not mix.
> - **AI provider processing:** Document excerpts and test questions are sent over HTTPS to the configured AI API (OpenAI or Anthropic) to create search embeddings and generate cited answers.
>   Standard API terms apply, where API inputs are not used by those providers to train foundation models.
> - **Human in the loop:** Nothing is ever sent directly to your customers.
>   Chat answers stay inside the internal workspace, and both agent ticket escalations and n8n email drafts pause for a human on your team to review, edit, and send.
> - **Deletion:** This is a self-hosted pilot environment.
>   At the end of the pilot - or whenever you ask - your uploaded documents, search vectors, chat history, and tickets can be deleted permanently.

## 3. Sample outreach snippet

Use this template for a warm message to a shop owner, clinic manager, agency lead, or friend running a small support inbox:

```text
Subject: Free 2-week pilot - cited AI answers from your support docs?

Hi <Name>,

I built an internal support copilot for small teams and I am onboarding one business for a free 2-week pilot to test it on real support workflows.

How it works:
- We load 3 to 5 of your existing FAQ or policy docs (refunds, pricing, shipping/booking, common troubleshooting) or crawl your public FAQ page.
- Your team asks questions on web or mobile and gets answers with exact quotes from your docs.
- When the docs do not cover something, it says "I don't know" instead of guessing, or opens a review ticket / Slack draft for a human to approve. Nothing is ever sent to customers automatically.

What I need from you:
1. 3 to 5 policy or FAQ files (PDF, Markdown, or public FAQ URLs - no customer personal data needed).
2. 15 minutes for me to hand over your login and walk through 10 real customer questions together.
3. Brief honest feedback after a week on whether the answers and drafts actually save time.

Would you be open to trying this next week with a few of your support docs?

Best,
Nate
```

## 4. Onboarding runbook

1. **Verify the live VPS stack:** confirm `curl https://<DOMAIN>/api/health` returns `{"status":"ok"}` and TLS renewal passed `--dry-run`.
2. **Create a dedicated partner account:** register `<partner>@...` in the web admin UI, and set `DRAFT_USER_EMAIL` to that email in `.env` if connecting the n8n Slack draft workflow.
3. **Scrub and normalize files:** skim every file from the partner to confirm there is no customer PII, and convert messy Word exports to clean Markdown with clear `#` / `##` headings when possible.
4. **Ingest documents:** upload each `.md` or `.pdf` file (or crawl public FAQ URLs) from the `Documents` page and record the returned document IDs.
5. **Inspect chunk boundaries:** open the `Chunks` page for each document ID and verify that headings, numbers, and policy tables stayed readable inside `parent_child` chunks.
6. **Build the partner golden set:** copy `backend/evals/golden_set.partner.template.json` to an untracked local file such as `backend/evals/golden_set.partner.json`, replace the questions and verbatim substrings using the partner's Markdown docs in a local partner fixtures folder, and run the offline eval snippet below from `backend/`.
7. **Run the 10 seed questions live:** walk through the seed list below in `Chat` (`RAG` mode) and verify citations, numbers, and clean refusals before handing credentials to the partner.
8. **Test human-in-the-loop escalation:** switch `Chat` to `Agent` mode, ask an unresolved order or exception question, confirm a ticket is created in `awaiting_human` state, and resolve it on the `Tickets` tab.
9. **Hand over access (15 minutes):** share the web URL (and Expo Go setup if mobile is helpful), watch the partner ask 3 of their own recent customer questions without coaching, and note every phrasing gap.
10. **Grow to 30 questions in week 1:** turn missed phrasings and new edge cases into rows in `golden_set.partner.json` before tuning chunk strategy or `RETRIEVAL_MIN_SCORE`.

Partner golden-set eval command (run from `backend/`):

```bash
PYTHONPATH=. python -c '
import asyncio
from pathlib import Path
from evals.harness import build_embedder, evaluate, find_variant, load_golden
from evals.run_eval import build_eval_llm, format_report

report = asyncio.run(evaluate(
    find_variant("parent_child@128/512"),
    build_embedder("openai"),
    load_golden(Path("evals/golden_set.partner.json")),
    llm=build_eval_llm("configured"),
    fixtures_dir=Path("evals/partner_fixtures"),
))
print(format_report(report))
'
```

## 5. Ten seed questions for day-one verification

Adapt the nouns in brackets (`[order / booking / plan]`) to the partner's business, and align each row with `backend/evals/golden_set.partner.template.json`:

1. **Refund or cancellation window (`partner-refund-window`):** "How many days after `[purchase / booking]` can a customer request a refund or cancel?" - expects cited day count and eligibility rule.
2. **Pricing and plan breakdown (`partner-pricing-tiers`):** "What does each `[plan / service package]` cost and what is included?" - expects cited prices and limits with exact numbers verified.
3. **Turnaround or shipping speed (`partner-turnaround-time`):** "How long does standard `[shipping / delivery / onboarding]` take, and is there an expedited option?" - expects cited business-day window and fee.
4. **Multi-section policy synthesis (`partner-cancel-and-payout`):** "If a customer cancels today, when does cancellation take effect and how many business days until the refund arrives?" - expects citations spanning both cancellation and payout sections.
5. **Accepted payment methods and invoices (`partner-payment-methods`):** "Which payment methods do you accept and how can a customer get an invoice or receipt?" - expects cited payment options and billing instructions.
6. **First-line troubleshooting or prep step (`partner-troubleshooting-step`):** "A customer says `[common issue or pre-visit question]` - what steps should they follow first?" - expects ordered steps grounded in the guide.
7. **Warranty or explicit exclusion (`partner-policy-exclusion`):** "Is `[common excluded scenario, e.g. accidental damage / downloaded file / late no-show]` covered for a free replacement or refund?" - expects a clear "no" backed by the exclusion clause.
8. **Reaching a human (`partner-human-contact`):** "How can a customer reach a live person and what are the support hours?" - expects cited contact channel and response window.
9. **Unstated policy gap (`partner-missing-discount`, refusal test):** "Do you offer a `[student / nonprofit / wholesale]` discount?" (pick a discount absent from their docs) - must **refuse** rather than invent a policy.
10. **Off-topic or private request (`partner-off-topic`, refusal test):** "What is the owner's personal cell phone number?" (or an unrelated trivia question) - must **refuse** cleanly with zero fabricated details.

**Bonus agent check (not in RAG golden set):** in `Agent` mode, ask "Order `#99999` has not arrived and the customer wants an immediate refund" and confirm the assistant runs `lookup_order`, opens a human review ticket via `create_ticket`, and pauses until approved or rejected.

## 6. Success metrics

### Primary user-value bar (pilot pass/fail)

- **Active real usage:** the partner (or their support staff) runs at least **10 real customer questions or inbound ticket drafts** through the copilot within 7 days.
- **Draft usefulness:** at least **70% of answers or Slack drafts** are rated usable as-is or with minor wording tweaks during the end-of-week check-in.
- **Qualitative time-saved signal:** one concrete written note from the partner naming what helped (for example faster policy lookup for a junior staff member or faster first-draft replies) plus the top 2 gaps to fix next.

### Technical quality and cost guardrails

- **Zero hallucinated policy claims:** 0 instances of invented prices, deadlines, or promises across reviewed pilot sessions (enforced by verbatim quote and number verification in `backend/app/rag/generate.py`).
- **Partner eval thresholds (10 seed questions on day 1, expanded to ~30 by day 7):**
  - `hit_rate@3 >= 0.85` on answerable partner questions with `OpenAIEmbedder`.
  - `correct_refusal_rate == 1.00` on unanswerable and off-topic questions.
  - `false_refusal_rate <= 0.20` on answerable questions (investigate missing synonyms or PDF formatting first when higher).
- **Latency and cost bounds:** p95 chat latency under **8 seconds** and mean LLM + embedding cost under **$0.01 per query** on `gpt-4o-mini` or `claude-haiku-4-5`.
