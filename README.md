# Agent-first PMO

An AI business analyst that turns meeting transcripts into draft requirements, decisions, action items and open questions, then puts every draft in front of a human before anything becomes a work item.

**Status:** first working version (v0.1). Runs locally from the command line with the offline extractor. The Bedrock and OpenAI-compatible model clients are written but have not yet been run against a live model.

## Why this exists

Most PMO tooling is a database with a form on top. The analysis work, listening to a meeting and turning it into clear requirements, still falls on people. This project starts from the other end: an agent drafts that analysis, and people accept, edit or reject it.

The goal is not to replace a business analyst end to end. It is to take a dependable slice of the role off every analyst's plate, starting with one function, measuring it, and only widening scope once the numbers hold.

## What it does today

1. **Parses transcripts:** Teams-style WebVTT (`<v Speaker>` tags) and plain `Name: text` files. Back-to-back cues from the same speaker are merged into one turn.
2. **Resolves speakers:** meeting tools label people inconsistently ("Ortiz, Dana (Guest)", "Dana O.", "Speaker 3", a phone number). A roster with aliases and manual overrides maps labels to people by exact name, alias, email, "Last, First" order or fuzzy match. Anything it can't place is flagged, never guessed.
3. **Drafts artifacts:** each draft has a kind, one sentence of text, a confidence score and links to the exact transcript segments it came from.
4. **Stores a graph:** people, meetings, segments, drafts and work items, with typed relationships, so any work item can be traced back to who said what and when.
5. **Gates on human review:** nothing becomes a work item until someone accepts it. Edits and rejections are recorded with the reason.
6. **Measures the pilot:** acceptance rate (accepted as-is plus accepted with edits, over all reviewed) against a 70% target.
7. **Exports one way:** builds the exact Azure DevOps (JSON Patch) and Jira request bodies for accepted work items and writes them to a file. This version is a dry run and sends nothing.
8. **Applies retention:** purges transcript text older than N days while keeping drafts, decisions and traceability.

## Architecture

```
transcript (.vtt / .txt)
   -> transcript.py   parse into speaker segments
   -> speakers.py     resolve labels to people (roster, aliases, overrides, fuzzy)
   -> extraction.py   HeuristicExtractor (offline) or LLMExtractor (any LLMClient)
   -> graph.py        property graph in SQLite: nodes + typed edges
   -> review.py       accept / edit / reject, acceptance metric, trace
   -> sync.py         one-way export payloads for Azure DevOps or Jira (dry run)
```

Graph model:

```
(Person)-[:ATTENDED]->(Meeting)
(Segment)-[:PART_OF]->(Meeting)
(Segment)-[:SPOKEN_BY]->(Person)
(Draft)-[:DERIVED_FROM]->(Segment)
(Draft)-[:RAISED_BY]->(Person)
(Draft)-[:FROM_MEETING]->(Meeting)
(Draft)-[:BECAME]->(WorkItem)
```

**Design decisions**

- **Human in the loop by default.** Drafts are proposals. Review outcomes are stored, which is what makes the acceptance target measurable.
- **Evidence on every draft.** A draft that can't point at the segments it came from is dropped. LLM output is validated (kind, text, segment numbers, confidence) and anything malformed is discarded with a warning rather than repaired by guessing.
- **Explicit speaker resolution.** Extraction runs on resolved people, not on the meeting tool's labels.
- **Graph, not tables.** The questions a PM asks (who asked for this, what else did that meeting decide) are traversals. The graph lives in one SQLite file so the proof of concept needs no server; `GraphStore` is the seam for a hosted graph database later.
- **Pluggable models.** The extractor talks to an `LLMClient` with one method, `complete(system, prompt)`. Included: Amazon Bedrock (Converse API) and any OpenAI-compatible endpoint, which covers local models via Ollama or LM Studio. An offline heuristic extractor runs with no model at all and serves as the baseline the LLM has to beat.
- **One-way sync.** The team's tracker stays the system of record. Accepted items are pushed out; nothing is read back.
- **Standard library only.** The core has no third-party dependencies. `boto3` is optional, for Bedrock.

## Getting started

Needs Python 3.10 or later.

```
git clone https://github.com/Brad-Land/agent-first-pmo.git
cd agent-first-pmo
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Run the sample meeting end to end (made-up people and data):

```
pmo ingest samples/kickoff.vtt --roster samples/roster.json --title "Purchase portal kickoff" --date 2026-11-20
pmo drafts
pmo accept <draft-id>
pmo accept <draft-id> --text "Route requests over $5,000 to finance for a second approval."
pmo reject <draft-id> --reason "duplicate"
pmo metrics
pmo trace wi-0001
pmo export --target ado --org <your-org> --project <your-project>
pmo purge --older-than-days 30
```

The sample includes a speaker the roster can't place (a phone number), so you can see unresolved speakers being flagged.

### Using a model instead of the offline extractor

Copy `.env.example` to `.env`, set the values, and load them into your shell.

- **Amazon Bedrock:** `pip install -e ".[bedrock]"`, set `PMO_BEDROCK_MODEL_ID` and `AWS_REGION`, have AWS credentials configured, then `pmo ingest ... --extractor bedrock`.
- **Local or bring-your-own model:** run any OpenAI-compatible server (for example Ollama), set `PMO_OPENAI_BASE_URL` and `PMO_OPENAI_MODEL`, then `pmo ingest ... --extractor openai`.

Long transcripts are sent in chunks of 80 segments.

### Tests

```
pytest
```

The suite covers parsing, speaker resolution, extraction and LLM-output validation (with a fake model), the review gate, the acceptance metric, traceability, export payloads and retention.

## Data handling

This version is built and tested with made-up sample transcripts. It applies no PII redaction and no access control, and stores everything in a local SQLite file. Before it touches real meetings it needs redaction, access control and a set retention period (the purge command is the starting point).

## Roadmap

- Run the LLM extractor against Bedrock and a local model on real-shaped transcripts and compare acceptance with the heuristic baseline
- Ingest transcripts automatically through a connector or agent instead of manual upload
- Send exports to Azure DevOps (free tier) and Jira for real, behind the same one-way interface
- A review screen in place of the command line
- Hosted deployment on AWS or Azure, with a hosted graph database behind `GraphStore`
- PII redaction, access control and retention settings for real meeting data
- Extend from the business analyst role to other PMO functions, one slice at a time

## About

Built by Brad Landrum as an independent project, on personal hardware and accounts, outside any employer.
