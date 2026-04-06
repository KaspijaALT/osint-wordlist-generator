# OSINT Wordlist Generator

A flexible and efficient wordlist generator built for OSINT and defensive security work.

This tool helps generate targeted wordlists based on real-world data like names, keywords, and patterns — instead of relying only on static lists like rockyou.txt.

It’s designed to be practical, customizable, and safe to use with built-in limits to avoid generating massive unusable files.

---

## Why I built this

Most wordlists are either:
- too generic  
- too large  
- or not tailored to real targets  

I wanted something that:
- adapts to specific data (names, emails, etc.)
- gives full control over how combinations are generated
- doesn’t accidentally create millions of useless entries

---

## Features

- CLI + interactive mode
- Token input from CLI or file
- Two generation modes:
  - **Permutation** (no repetition)
  - **Product** (with repetition)
- Custom separators (`.`, `_`, `-`, etc.)
- Prefixes and suffixes support
- Year ranges (e.g. `1990-2025`)
- Case transformations:
  - lower / upper / title / as-is
  - full per-letter case variation (for short words)
- Leetspeak variations (limited to avoid explosion)
- Subtoken extraction (splits words like emails/domains)
- "Half" mode (uses partial tokens)
- Random sampling mode (generate realistic subsets instead of everything)
- Streaming output (low memory usage)
- Built-in safety limits to prevent huge outputs

---

## Installation

```bash
git clone git@github.com:KaspijaALT/osint-wordlist-generator.git
cd osint-wordlist-generator
