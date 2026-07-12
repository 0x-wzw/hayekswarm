# HayekSwarm — Research LLM Wiki Integration

This skill integrates Karpathy's LLM Wiki pattern into the HayekSwarm marketplace.
Agents can build, query, and maintain a persistent knowledge base as interlinked
markdown files, and the wiki content feeds into the economic engine's context.

## How It Works

1. **Wiki as agent memory** — The wiki serves as persistent, compounding knowledge
   that all council agents can reference during auctions and task execution.

2. **Wiki tasks in the marketplace** — Users submit wiki-related tasks (ingest,
   query, lint) through the marketplace API, and council agents bid on them.

3. **Cross-referencing** — Wiki entities (people, concepts, papers) are indexed
   by dimension, so the Synthesis agent (D1) can find cross-domain connections
   that individual agents might miss.

## Setup

```bash
# Set wiki path
export WIKI_PATH="$HOME/wiki"

# Create initial wiki structure
mkdir -p "$WIKI_PATH"/{raw/{articles,papers,transcripts,assets},entities,concepts,comparisons,queries}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/wiki/ingest` | POST | Ingest a source (URL, file, text) into the wiki |
| `/api/wiki/query` | POST | Query the wiki with a natural language question |
| `/api/wiki/lint` | GET | Check wiki health and consistency |
| `/api/wiki/search` | GET | Search wiki pages by keyword |
| `/api/wiki/stats` | GET | Wiki statistics (pages, entities, cross-refs) |

## Wiki Structure

```
wiki/
├── SCHEMA.md          # Conventions, structure rules
├── index.md           # Sectioned content catalog
├── log.md             # Chronological action log
├── raw/               # Layer 1: Immutable source material
│   ├── articles/
│   ├── papers/
│   ├── transcripts/
│   └── assets/
├── entities/          # Layer 2: People, orgs, products, models
├── concepts/          # Layer 2: Concept/topic pages
├── comparisons/       # Layer 2: Side-by-side analyses
└── queries/           # Layer 2: Filed query results
```

## Agent Integration

When a wiki-related task enters the marketplace:

1. **D1 (Synthesis)** — Best for cross-domain queries and synthesis
2. **D6 (Analysis)** — Best for data extraction and comparison
3. **D7 (General)** — Best for general wiki maintenance
4. **D9 (Research)** — Best for deep research and paper ingestion

The winning agent reads the wiki orientation files (SCHEMA.md, index.md, log.md)
before executing, ensuring context-aware responses.
