#!/usr/bin/env python3
"""
OSINT-style wordlist generator.

Features:
- CLI (argparse) + interactive mode
- Read tokens from CLI or from a file
- Permutations (no repetition) and product (with repetition) mixing modes
- Separators, prefixes, suffixes, year ranges, numeric append/prepend
- Case handling: lower/upper/title/asis and FULL per-letter casing for short tokens
- "half" option: include prefixes up to half the token length
- "subtokens" (split on non-alnum) inclusion
- Leet substitutions (configurable depth)
- Streaming output to disk (low memory)
- Safety controls: max_entries default 100_000, dry-run to estimate combinations
- Optional random sampling instead of exhaustive generation
- Progress logging
- Ethical/legal reminder

Use responsibly: only on systems/data you own or have explicit authorization to test.
"""

from __future__ import annotations
import argparse
import itertools
import math
import re
import sys
import random
from pathlib import Path
from typing import Iterable, List, Set, Tuple

# -----------------------
# Configuration & helpers
# -----------------------
LEET_MAP = {
    "a": ["4", "@"],
    "b": ["8"],
    "e": ["3"],
    "g": ["9"],
    "i": ["1", "!"],
    "l": ["1", "7"],
    "o": ["0"],
    "s": ["5", "$"],
    "t": ["7"],
    "z": ["2"],
}

SAFE_DEFAULT_MAX = 100_000  # default cap to prevent runaway
FULL_CASE_MAX_LEN = 6       # only do per-letter case permutations for tokens shorter than this by default

non_alnum_re = re.compile(r'[^A-Za-z0-9]')

def parse_range_or_list(s: str) -> List[str]:
    s = s.strip()
    if not s:
        return []
    if '-' in s and ',' not in s:
        parts = s.split('-', 1)
        try:
            a = int(parts[0]); b = int(parts[1])
            return [str(y) for y in range(a, b+1)]
        except:
            return [p.strip() for p in s.split(',') if p.strip()]
    return [p.strip() for p in s.split(',') if p.strip()]

def read_tokens_from_file(path: Path) -> List[str]:
    out = []
    with path.open('r', encoding='utf-8', errors='ignore') as fh:
        for line in fh:
            t = line.strip()
            if t:
                out.append(t)
    return out

def split_subtokens(token: str) -> List[str]:
    # split on non-alnum and keep alnum parts
    parts = re.split(non_alnum_re, token)
    return [p for p in parts if p]

def case_variants(token: str, modes: List[str], full_case_max_len: int = FULL_CASE_MAX_LEN) -> Iterable[str]:
    """Yield case variants for a token.
       modes can include 'lower','upper','title','asis','allcases' (allcases: every per-letter casing if short)."""
    seen = set()
    token = token.strip()
    basic = []
    for m in modes:
        if m == 'lower':
            basic.append(token.lower())
        elif m == 'upper':
            basic.append(token.upper())
        elif m == 'title':
            basic.append(token.title())
        elif m == 'asis':
            basic.append(token)
    for b in basic:
        if b not in seen:
            seen.add(b)
            yield b

    if 'allcases' in modes and len(token) <= full_case_max_len:
        # generate all per-letter casing combos (2^n)
        n = len(token)
        for mask in range(1 << n):
            s = []
            for i, ch in enumerate(token):
                if ch.isalpha() and (mask & (1 << i)):
                    s.append(ch.upper())
                else:
                    s.append(ch.lower())
            v = ''.join(s)
            if v not in seen:
                seen.add(v)
                yield v

def leet_variants(token: str, max_variants: int = 12) -> List[str]:
    """Produce a small set of leet variants (limited)."""
    token = token.strip()
    chars = list(token)
    idxs = [i for i,ch in enumerate(chars) if ch.lower() in LEET_MAP]
    variants = set([token])
    # single substitutions
    for i in idxs:
        for rep in LEET_MAP[chars[i].lower()]:
            t = chars.copy()
            t[i] = rep
            variants.add(''.join(t))
            if len(variants) >= max_variants:
                return list(variants)
    # double substitutions
    for a,b in itertools.combinations(idxs, 2):
        for r1 in LEET_MAP[chars[a].lower()]:
            for r2 in LEET_MAP[chars[b].lower()]:
                t = chars.copy()
                t[a]=r1; t[b]=r2
                variants.add(''.join(t))
                if len(variants) >= max_variants:
                    return list(variants)
    return list(variants)

# -----------------------
# Generation strategies
# -----------------------
def generate_token_pool(base_tokens: List[str],
                        include_subtokens: bool=False,
                        include_half: bool=False,
                        half_min_len: int = 3,
                        leet: bool=False,
                        case_modes: List[str]=['lower','asis']) -> List[str]:
    """
    Expand base_tokens into a token pool:
     - optionally add subtokens
     - optionally add prefixes (half-mode)
     - optionally add leet variants
     - case variants are applied later during write step to control explosion
    """
    pool = []
    for t in base_tokens:
        t = t.strip()
        if not t:
            continue
        pool.append(t)
        if include_subtokens:
            subs = split_subtokens(t)
            for s in subs:
                if s and s not in pool:
                    pool.append(s)
        if include_half and len(t) >= half_min_len:
            half_len = max(1, len(t)//2)
            prefix = t[:half_len]
            if prefix and prefix not in pool:
                pool.append(prefix)
        if leet:
            lv = leet_variants(t, max_variants=8)
            for v in lv:
                if v not in pool:
                    pool.append(v)
    # deduplicate preserving order
    seen = set()
    out = []
    for x in pool:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

def estimate_count(token_pool: List[str],
                   max_concat: int,
                   separators: List[str],
                   years: List[str],
                   prefixes: List[str],
                   suffixes: List[str],
                   case_modes: List[str],
                   per_letter_allcase_len: int,
                   mode: str,
                   allow_repeat: bool) -> int:
    """
    Rough combinatorial estimate (may be high for allcases).
    mode: 'permutation' or 'product'
    allow_repeat: product = with repetition; permutation = without repetition
    """
    base = len(token_pool)
    if base == 0:
        return 0
    token_combo_count = 0
    if mode == 'product':
        for L in range(1, max_concat+1):
            token_combo_count += (base ** L)
    else:  # permutations without repetition
        for L in range(1, min(max_concat, base)+1):
            token_combo_count += math.perm(base, L) if hasattr(math, 'perm') else math.factorial(base)//math.factorial(base-L)
    # separators multiply choices
    sep_count = len(separators)
    # years optional (including empty)
    year_count = max(1, 1 + len(years))
    pre_count = max(1, len(prefixes))
    suf_count = max(1, len(suffixes))
    # case expansion: approximate
    case_mult = 1
    # if allcases in modes, estimate worst-case 2^n for short tokens - we approximate by 4x multiplier for safety (user warned)
    if 'allcases' in case_modes:
        case_mult = 4
    else:
        case_mult = len(set(case_modes)) if case_modes else 1
    est = token_combo_count * sep_count * year_count * pre_count * suf_count * case_mult
    return est

# -----------------------
# Core writer
# -----------------------
def stream_generate(output_path: Path,
                    token_pool: List[str],
                    separators: List[str],
                    years: List[str],
                    prefixes: List[str],
                    suffixes: List[str],
                    max_concat: int,
                    case_modes: List[str],
                    leet: bool,
                    mode: str,
                    allow_repeat: bool,
                    min_len: int,
                    max_len: int,
                    max_entries: int,
                    random_sample: int = 0,
                    progress_every: int = 5000) -> int:
    """
    Stream generated entries to disk. Returns number written.
    mode: 'product' or 'permutation'
    allow_repeat: if True, repeat allowed even in permutation mode (acts like product)
    random_sample: if >0, write only that many random unique candidates (sampling approach)
    """
    written = 0
    out_fh = output_path.open('w', encoding='utf-8', errors='ignore')
    try:
        # Create the base iterable of token sequences
        # If random_sample requested, we'll produce candidate_count then sample without storing entire set:
        if random_sample > 0:
            # In sampling mode, we will repeatedly randomly build candidates until we collect random_sample unique entries or reach max_entries attempts.
            seen = set()
            attempts = 0
            max_attempts = max_entries * 100 if max_entries else 1_000_000
            while len(seen) < random_sample and attempts < max_attempts:
                L = random.randint(1, max_concat)
                if mode == 'product' or allow_repeat:
                    combo = tuple(random.choice(token_pool) for _ in range(L))
                else:
                    if L > len(token_pool):
                        combo = tuple(random.choices(token_pool, k=L))
                    else:
                        combo = tuple(random.sample(token_pool, k=L))
                sep = random.choice(separators)
                cand = sep.join(combo)
                # apply year sometimes
                y = random.choice(years) if years and random.random() < 0.6 else ""
                base_with_year = cand + (y if y else "")
                pre = random.choice(prefixes)
                suf = random.choice(suffixes)
                candidate2 = f"{pre}{base_with_year}{suf}"
                # case variants: choose one variant at random
                variants = list(case_variants(candidate2, case_modes))
                choice_variant = random.choice(variants) if variants else candidate2
                # leet maybe
                if leet and random.random() < 0.4:
                    lv = leet_variants(choice_variant, max_variants=3)
                    choice_variant = random.choice(lv)
                if (min_len and len(choice_variant) < min_len) or (max_len and len(choice_variant) > max_len):
                    attempts += 1
                    continue
                if choice_variant not in seen:
                    seen.add(choice_variant)
                    out_fh.write(choice_variant + '\n')
                    written += 1
                attempts += 1
                if max_entries and written >= max_entries:
                    break
            return written

        # Exhaustive mode
        for L in range(1, max_concat+1):
            # build sequences:
            if mode == 'product' or allow_repeat:
                seq_iter = itertools.product(token_pool, repeat=L)
            else:
                if L > len(token_pool):
                    # fallback to product if L > pool
                    seq_iter = itertools.product(token_pool, repeat=L)
                else:
                    seq_iter = itertools.permutations(token_pool, L)
            for combo in seq_iter:
                for sep in separators:
                    candidate = sep.join(combo)
                    # years (include none)
                    year_options = [""] + years if years else [""]
                    for y in year_options:
                        base_with_year = candidate + (y if y else "")
                        for pre in prefixes:
                            for suf in suffixes:
                                candidate2 = f"{pre}{base_with_year}{suf}"
                                # case variants
                                for variant in case_variants(candidate2, case_modes):
                                    final = variant
                                    # optionally add leet variant(s)
                                    if leet:
                                        # produce a few small leet variants (but not explode)
                                        for lv in leet_variants(final, max_variants=3):
                                            if (min_len and len(lv) < min_len) or (max_len and len(lv) > max_len):
                                                continue
                                            out_fh.write(lv + '\n'); written += 1
                                            if written % progress_every == 0:
                                                print(f"[+] wrote {written} entries...")
                                            if max_entries and written >= max_entries:
                                                return written
                                    else:
                                        if (min_len and len(final) < min_len) or (max_len and len(final) > max_len):
                                            continue
                                        out_fh.write(final + '\n'); written += 1
                                        if written % progress_every == 0:
                                            print(f"[+] wrote {written} entries...")
                                        if max_entries and written >= max_entries:
                                            return written
        return written
    finally:
        out_fh.close()

# -----------------------
# CLI / interactive
# -----------------------
def interactive_prompt():
    print("Improved OSINT wordlist generator (defensive use only).")
    print("WARNING: generating every possible combination can create huge files; use limits.")
    print()
    def ask(prompt, default=''):
        r = input(f"{prompt} [{default}]: ").strip()
        return r if r else default

    # tokens
    f = ask("Enter path to a token file (one token per line) OR leave blank to type tokens now", "")
    if f:
        tokens = read_tokens_from_file(Path(f))
    else:
        s = ask("Enter tokens (comma separated)", "")
        tokens = [t.strip() for t in s.split(',') if t.strip()]

    # extras
    extras = ask("Additional keywords (comma separated)", "")
    if extras:
        tokens += [t.strip() for t in extras.split(',') if t.strip()]

    # options
    case_modes = ask("Case modes (comma: lower,upper,title,asis,allcases) [lower,asis]", "lower,asis")
    case_modes = [c.strip() for c in case_modes.split(',') if c.strip()]

    leet = ask("Enable leet variants? (y/N)", "N").lower().startswith('y')
    subtokens = ask("Include subtokens (split on non-alnum)? (y/N)", "N").lower().startswith('y')
    half = ask("Include 'half' prefixes of tokens? (y/N)", "N").lower().startswith('y')

    separators = ask("Separators (comma separated; use '' for empty). Example: ,,_,- [default '']", "")
    if separators == "":
        separators = [""]
    else:
        separators = [s if s != "''" else "" for s in separators.split(',')]

    years = ask("Years (comma or range like 1990-1995)", "")
    years = parse_range_or_list(years)

    prefixes = ask("Prefixes (comma separated) or leave blank", "")
    prefixes = [p for p in prefixes.split(',') if p.strip()] or [""]

    suffixes = ask("Suffixes (comma separated) or leave blank (e.g. !,123)", "")
    suffixes = [s for s in suffixes.split(',') if s.strip()] or [""]

    max_concat = int(ask("Max tokens to concatenate (1-4 recommended)", "2"))
    mode = ask("Mixing mode: 'permutation' (no repetition) or 'product' (with repetition)", "permutation")
    allow_repeat = mode == 'product'

    min_len = int(ask("Min length (0 for none)", "0") or "0") or None
    max_len = int(ask("Max length (0 for none)", "0") or "0") or None

    max_entries = int(ask(f"Maximum entries to write (0 for no cap) [default {SAFE_DEFAULT_MAX}]", str(SAFE_DEFAULT_MAX)))
    if max_entries == 0:
        max_entries = None

    out = ask("Output filename", "improved_wordlist.txt")

    random_sample = int(ask("Random sample size (0 for exhaustive)", "0"))

    # summary & confirm
    print("\nSummary:")
    print(f"Tokens: {len(tokens)} tokens")
    print(f"Separators: {separators}")
    print(f"Years: {years[:10]}{'...' if len(years)>10 else ''}")
    print(f"Prefixes: {prefixes}")
    print(f"Suffixes: {suffixes}")
    print(f"Max concat: {max_concat}")
    print(f"Mode: {mode}")
    print(f"Leet: {leet}, subtokens: {subtokens}, half: {half}")
    print(f"Case modes: {case_modes}")
    print(f"Min/Max len: {min_len}/{max_len}")
    print(f"Max entries cap: {max_entries}")
    print(f"Random sample: {random_sample}")
    print(f"Output file: {out}")
    ok = ask("Proceed? (Y/n)", "Y")
    if ok.lower().startswith('n'):
        print("Aborted.")
        return

    # build pool and run
    pool = generate_token_pool(tokens, include_subtokens=subtokens, include_half=half, leet=False, case_modes=case_modes)
    est = estimate_count(pool, max_concat, separators, years, prefixes, suffixes, case_modes, FULL_CASE_MAX_LEN, mode, allow_repeat)
    print(f"Estimated combinations (rough): {est}")
    if est > 2_000_000 and (not max_entries or max_entries > SAFE_DEFAULT_MAX):
        confirm = ask(f"Estimated size is large ({est}). Continue? (y/N)", "N")
        if not confirm.lower().startswith('y'):
            print("Aborted due to large estimate.")
            return

    written = stream_generate(Path(out), pool, separators, years, prefixes, suffixes, max_concat,
                               case_modes, leet, mode, allow_repeat,
                               min_len, max_len, max_entries, random_sample)
    print(f"[+] Finished. Wrote {written} entries to {out}")

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Improved OSINT wordlist generator (defensive use only).")
    p.add_argument('--tokens-file', '-f', type=Path, help="File with one token per line.")
    p.add_argument('--tokens', '-t', type=str, help="Comma separated tokens.")
    p.add_argument('--extras', type=str, default="", help="Comma separated extra keywords.")
    p.add_argument('--separators', type=str, default="", help="Comma separated separators; use '' for empty.")
    p.add_argument('--years', type=str, default="", help="Comma list or range like 1990-1995.")
    p.add_argument('--prefixes', type=str, default="", help="Comma separated prefixes.")
    p.add_argument('--suffixes', type=str, default="", help="Comma separated suffixes.")
    p.add_argument('--max-concat', type=int, default=2)
    p.add_argument('--mode', choices=['permutation','product'], default='permutation')
    p.add_argument('--case-modes', type=str, default='lower,asis', help="lower,upper,title,asis,allcases")
    p.add_argument('--leet', action='store_true')
    p.add_argument('--subtokens', action='store_true')
    p.add_argument('--half', action='store_true', help="Include prefixes up to half token length")
    p.add_argument('--min-len', type=int, default=0)
    p.add_argument('--max-len', type=int, default=0)
    p.add_argument('--max-entries', type=int, default=SAFE_DEFAULT_MAX)
    p.add_argument('--output', '-o', type=Path, default=Path('improved_wordlist.txt'))
    p.add_argument('--random-sample', type=int, default=0, help="Create a random sample of this many entries instead of exhaustive.")
    p.add_argument('--no-interactive', action='store_true')
    return p

def run_cli(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if not args.no_interactive and not (args.tokens_file or args.tokens):
        interactive_prompt()
        return

    # gather tokens
    tokens = []
    if args.tokens_file:
        tokens += read_tokens_from_file(args.tokens_file)
    if args.tokens:
        tokens += [t.strip() for t in args.tokens.split(',') if t.strip()]
    if args.extras:
        tokens += [t.strip() for t in args.extras.split(',') if t.strip()]
    if not tokens:
        print("[!] No tokens provided. Use --tokens or --tokens-file or run without args for interactive mode.")
        return

    separators = [s if s != "''" else "" for s in args.separators.split(',')] if args.separators else [""]
    years = parse_range_or_list(args.years)
    prefixes = [p for p in args.prefixes.split(',') if p.strip()] or [""]
    suffixes = [s for s in args.suffixes.split(',') if s.strip()] or [""]

    case_modes = [c.strip() for c in args.case_modes.split(',') if c.strip()]

    pool = generate_token_pool(tokens, include_subtokens=args.subtokens, include_half=args.half, leet=False, case_modes=case_modes)
    est = estimate_count(pool, args.max_concat, separators, years, prefixes, suffixes, case_modes, FULL_CASE_MAX_LEN, args.mode, args.mode=='product')
    print(f"[+] Token pool size: {len(pool)}  Rough estimate: {est}")
    if est > 2_000_000 and args.max_entries is None:
        confirm = input(f"Estimated size {est} is very large. Continue? (y/N) ").strip().lower()
        if not confirm.startswith('y'):
            print("Aborted.")
            return

    written = stream_generate(args.output, pool, separators, years, prefixes, suffixes, args.max_concat,
                               case_modes, args.leet, args.mode, args.mode=='product',
                               args.min_len or None, args.max_len or None, args.max_entries or None,
                               args.random_sample)
    print(f"[+] Done. Wrote {written} entries to {args.output}")

if __name__ == '__main__':
    # Ethical reminder
    print("**ETHICS: Use this tool only for defensive/authorized testing and education.**")
    print("By continuing you confirm you will not use it to attack systems without permission.\n")
    run_cli()
