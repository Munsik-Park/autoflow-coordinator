#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Munsik-Park
# SPDX-License-Identifier: Apache-2.0
# =============================================================================
# Reviewer settings resolver
# =============================================================================
# Reads the reviewer settings file — each reviewer's model, effort, rule file
# and lenses file —, and maps the resolved values onto each reviewer CLI's
# flags. Sourced, not executed.
#
# The file is the reviewer-settings place the settings of the repository this
# library is in report; it is read anew on every run.
#
# File shape (every key optional; other keys are not read):
#
#   { "review": { "codex": { "model": "gpt-6-sol", "effort": "high",
#                            "rules": "<path>", "lenses": "<path>" } } }
#
# Supported reviewers: claude codex.
#
# Per reviewer, most specific first:
#   model  : .review.<name>.model > the reviewer's default (claude: opus;
#            codex: gpt-6-sol)
#   effort : the wrapper's --effort > .review.<name>.effort > inherit
#   rules  : .review.<name>.rules > review-<name>.md in the rule file folder
#            of this tree
#   lenses : .review.<name>.lenses > none
# "inherit" means NO flag is passed, so the CLI applies its own configuration.
# A relative rules or lenses path is read from the root of the tree this
# library is in, the tree the rule file folder belongs to (review_path).
#
# Unreadable conditions — settings that cannot be read as configured:
#   - the settings place cannot be reported (the lookup exits non-zero or
#     prints nothing)
#   - the file is present but jq is not on PATH
#   - the file is present but not valid JSON
#   - .review is present but not an object
#   - .review.<name> is present but not an object
#   - .review.<name>.model / .effort / .rules / .lenses is present but empty or
#     not a string
#   - .review.<name>.effort is a string outside that reviewer's vocabulary
# An explicit JSON `null` reads as absent. Only an absent file gives the
# defaults.
#
# The file is checked whole — every condition above, over every supported
# reviewer's settings — on every run, so every consumer reaches the same
# verdict on the same file. When it is unreadable, REVIEW_USER_STATE=unreadable:
# nothing in it applies, and the consumer prints the fixed marker line
# `user-config: UNREADABLE <file, or the lookup that failed> — <error>` and
# exits REVIEW_USER_UNREADABLE_EXIT (6) without launching a reviewer.
#
# Effort vocabularies (edit here when a CLI's set evolves): the values this
# wrapper accepts for --effort and .review.<name>.effort and passes to the CLI;
# a value outside the reviewer's list is refused before the CLI starts. The lists are
# not checked against the installed CLI.
#   claude : low medium high xhigh max
#   codex  : none minimal low medium high xhigh max ultra persistent
#
# API (all in the caller's scope):
#   resolve_reviewer_settings <tag> <name>
#       reads the settings when this process has not, and sets REVIEW_SOURCE
#       (user | none), REVIEW_CFG_PATH (the file, empty for none),
#       REVIEW_USER_CFG_PATH (the file, or the lookup when it failed),
#       REVIEW_USER_STATE (absent | ok | unreadable), REVIEW_USER_ERROR,
#       REVIEW_REVIEWER, REVIEW_MODEL, REVIEW_EFFORT (empty = inherit),
#       REVIEW_RULES and REVIEW_LENSES (empty = none) — the defaults, read
#       from no file, when REVIEW_USER_STATE is unreadable; exits 2 on an
#       unsupported name. <tag> is the caller's stderr prefix (e.g.
#       codex-review).
#   review_take_effort <tag> <value>
#       sets REVIEW_EFFORT to <value>, the wrapper's --effort, in place of the
#       resolved effort; exits 2 when <value> is outside the resolved
#       reviewer's vocabulary. Called after resolve_reviewer_settings.
#   review_path <value> <root>
#       prints <value> when absolute, else <root>/<value>.
#   review_readout
#       prints the `source:` and `user-config:` readout lines (stdout).
#   build_review_backend_args
#       sets the REVIEW_BACKEND_ARGS array — the exact CLI flags for the
#       resolved reviewer, model and effort:
#         claude : --model <m>  --effort <e>
#         codex  : --model <m>  -c model_reasoning_effort=<e>
#   review_config_summary
#       prints `model=<m> effort=<e|inherit>` — for the start marker; never an
#       env dump.
# =============================================================================

REVIEW_SUPPORTED_REVIEWERS="claude codex"
REVIEW_EFFORT_VOCAB_CLAUDE="low medium high xhigh max"
REVIEW_EFFORT_VOCAB_CODEX="none minimal low medium high xhigh max ultra persistent"
REVIEW_DEFAULT_MODEL_CLAUDE="opus"
REVIEW_DEFAULT_MODEL_CODEX="gpt-6-sol"
_REVIEW_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# The rule files of this tree, one per reviewer.
REVIEW_RULES_DIR="${_REVIEW_REPO_ROOT}/docs/review"
REVIEW_USER_UNREADABLE_EXIT=6

# Print the effort vocabulary for a reviewer (space-separated).
review_effort_vocab() {
  case "$1" in
    claude) printf '%s' "$REVIEW_EFFORT_VOCAB_CLAUDE" ;;
    codex)  printf '%s' "$REVIEW_EFFORT_VOCAB_CODEX" ;;
    *)      printf '' ;;
  esac
}

# Print the default model for a reviewer.
review_default_model() {
  case "$1" in
    claude) printf '%s' "$REVIEW_DEFAULT_MODEL_CLAUDE" ;;
    codex)  printf '%s' "$REVIEW_DEFAULT_MODEL_CODEX" ;;
    *)      printf '' ;;
  esac
}

_review_supported() {
  local n
  for n in $REVIEW_SUPPORTED_REVIEWERS; do
    [[ "$n" == "$1" ]] && return 0
  done
  return 1
}

# Read one optional string key `.review.<name>.<key>` into _REVIEW_OPT_VALUE
# (empty when the key is absent/null). Returns 1 (with a message on stderr via
# the caller's tag) when the key is present but empty or not a string. The
# value travels through a global rather than a command substitution so the
# failure return is observable under a caller's `set -e`.
_review_read_optional_string() {
  local tag="$1" cfg="$2" name="$3" key="$4" kind
  _REVIEW_OPT_VALUE=""
  kind="$(jq -r --arg b "$name" --arg k "$key" 'try (.review[$b][$k] | type) catch "unindexable"' "$cfg")"
  case "$kind" in
    null) return 0 ;;
    unindexable)
      echo "[${tag}] ${cfg} sets .review.${name} to a non-object, so .review.${name}.${key} cannot be read — refusing to launch the reviewer. Make it an object ({ \"model\": …, \"effort\": … }) or remove it." >&2
      return 1
      ;;
    string)
      _REVIEW_OPT_VALUE="$(jq -r --arg b "$name" --arg k "$key" '.review[$b][$k]' "$cfg")"
      if [[ -z "$_REVIEW_OPT_VALUE" ]]; then
        echo "[${tag}] ${cfg} sets an empty .review.${name}.${key} — refusing to launch the reviewer (an empty configured value must not be silently dropped). Set a value or remove the key." >&2
        return 1
      fi
      return 0
      ;;
    *)
      echo "[${tag}] ${cfg} sets .review.${name}.${key} to a ${kind}, expected a string — refusing to launch the reviewer. Set a string value or remove the key." >&2
      return 1
      ;;
  esac
}

# A present file requires jq and valid JSON; exits 2 otherwise.
_review_open_file() {
  local tag="$1" cfg="$2"
  if ! command -v jq >/dev/null 2>&1; then
    echo "[${tag}] ${cfg} is present but jq is not on PATH — refusing to guess the reviewer settings. Install jq or remove the file." >&2
    exit 2
  fi
  if ! jq -e . "$cfg" >/dev/null 2>&1; then
    echo "[${tag}] ${cfg} is present but not valid JSON — refusing to guess the reviewer settings. Fix or remove the file." >&2
    exit 2
  fi
}

# Parse one reviewer's model/effort/rules/lenses from <cfg> (empty <cfg> = no
# file) into REVIEW_MODEL / REVIEW_EFFORT / REVIEW_RULES / REVIEW_LENSES; exits 2
# on any unreadable condition.
_review_parse_settings() {
  local tag="$1" cfg="$2" name="$3"
  REVIEW_MODEL=""
  REVIEW_EFFORT=""
  REVIEW_RULES=""
  REVIEW_LENSES=""
  if [[ -n "$cfg" ]]; then
    _review_read_optional_string "$tag" "$cfg" "$name" model || exit 2
    REVIEW_MODEL="$_REVIEW_OPT_VALUE"
    _review_read_optional_string "$tag" "$cfg" "$name" effort || exit 2
    REVIEW_EFFORT="$_REVIEW_OPT_VALUE"
    _review_read_optional_string "$tag" "$cfg" "$name" rules || exit 2
    REVIEW_RULES="$_REVIEW_OPT_VALUE"
    _review_read_optional_string "$tag" "$cfg" "$name" lenses || exit 2
    REVIEW_LENSES="$_REVIEW_OPT_VALUE"
  fi
  [[ -n "$REVIEW_MODEL" ]] || REVIEW_MODEL="$(review_default_model "$name")"
  [[ -n "$REVIEW_RULES" ]] || REVIEW_RULES="${REVIEW_RULES_DIR}/review-${name}.md"

  if [[ -n "$REVIEW_EFFORT" ]]; then
    local vocab ok=0 e
    vocab="$(review_effort_vocab "$name")"
    for e in $vocab; do
      [[ "$e" == "$REVIEW_EFFORT" ]] && ok=1
    done
    if [[ "$ok" -ne 1 ]]; then
      echo "[${tag}] unsupported ${name} effort '${REVIEW_EFFORT}' in ${cfg} (.review.${name}.effort) — expected one of: ${vocab// /, }. Refusing to launch the reviewer; fix the value or remove the key to inherit." >&2
      exit 2
    fi
  fi
}

# The whole user-file check, run in a subshell so an unreadable condition is a
# verdict, not an exit: every condition, over every supported reviewer's
# settings. Prints `review` when `.review` is present.
_review_check_user_file() {
  local tag="$1" cfg="$2" n kind
  _review_open_file "$tag" "$cfg"
  kind="$(jq -r 'try (.review | type) catch "unindexable"' "$cfg")"
  case "$kind" in
    null) return 0 ;;
    object) ;;
    *)
      echo "[${tag}] ${cfg} sets .review to a ${kind}, expected an object — refusing to guess the reviewer settings. Make .review an object or remove it." >&2
      exit 2
      ;;
  esac
  for n in $REVIEW_SUPPORTED_REVIEWERS; do
    _review_parse_settings "$tag" "$cfg" "$n"
  done
  printf 'review'
}

# Read the operator file once per process. A lookup that fails or prints
# nothing is the unreadable result, never the absent one.
_review_select_source() {
  local tag="$1" user out rc lookup
  [[ "${_REVIEW_SOURCE_SELECTED:-0}" -eq 1 ]] && return 0
  REVIEW_SOURCE="none"
  REVIEW_CFG_PATH=""
  REVIEW_USER_STATE="absent"
  REVIEW_USER_ERROR=""
  lookup=(python3 "${_REVIEW_REPO_ROOT}/tools/config.py" reviewer-settings)
  user="$("${lookup[@]}" 2>/dev/null)" && rc=0 || rc=$?
  if [[ "$rc" -ne 0 || -z "$user" ]]; then
    REVIEW_USER_CFG_PATH="${lookup[*]}"
    REVIEW_USER_ERROR="$("${lookup[@]}" 2>&1 >/dev/null | tr '\n' ' ' | sed 's/ *$//' || true)"
    [[ -n "$REVIEW_USER_ERROR" ]] || REVIEW_USER_ERROR="exit ${rc}, printed no path"
    REVIEW_USER_STATE="unreadable"
    _REVIEW_SOURCE_SELECTED=1
    return 0
  fi
  REVIEW_USER_CFG_PATH="$user"
  if [[ -f "$user" ]]; then
    REVIEW_SOURCE="user"
    REVIEW_CFG_PATH="$user"
    # (`&& … ||` keeps a caller's `set -e` from exiting on the verdict.)
    out="$(_review_check_user_file "$tag" "$user" 2>&1)" && rc=0 || rc=$?
    if [[ "$rc" -ne 0 ]]; then
      REVIEW_USER_ERROR="$(printf '%s' "$out" | sed "s/^\[${tag}\] //" | tr '\n' ' ' | sed 's/ *$//')"
      REVIEW_USER_ERROR="${REVIEW_USER_ERROR#"$user "}"
      REVIEW_USER_STATE="unreadable"
    else
      REVIEW_USER_STATE="ok"
    fi
  fi
  _REVIEW_SOURCE_SELECTED=1
}

resolve_reviewer_settings() {
  local tag="$1" name="$2"
  REVIEW_REVIEWER="$name"
  REVIEW_MODEL=""
  REVIEW_EFFORT=""
  if ! _review_supported "$name"; then
    echo "[${tag}] unknown reviewer '${name}' — supported: ${REVIEW_SUPPORTED_REVIEWERS}." >&2
    exit 2
  fi
  _review_select_source "$tag"
  if [[ "$REVIEW_USER_STATE" == unreadable ]]; then
    _review_parse_settings "$tag" "" "$name"
  else
    _review_parse_settings "$tag" "$REVIEW_CFG_PATH" "$name"
  fi
}

review_path() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s/%s' "$2" "$1" ;;
  esac
}

# The readout lines every consumer prints: where the configuration came from,
# and the user file's state. `user-config: UNREADABLE …` is the fixed marker
# of the "user file unreadable" result.
review_readout() {
  case "$REVIEW_SOURCE" in
    none) echo "source: none" ;;
    *)    echo "source: ${REVIEW_SOURCE} ${REVIEW_CFG_PATH}" ;;
  esac
  case "$REVIEW_USER_STATE" in
    absent)     echo "user-config: absent${REVIEW_USER_CFG_PATH:+ ${REVIEW_USER_CFG_PATH}}" ;;
    ok)         echo "user-config: ok ${REVIEW_USER_CFG_PATH}" ;;
    unreadable) echo "user-config: UNREADABLE ${REVIEW_USER_CFG_PATH} — ${REVIEW_USER_ERROR}" ;;
  esac
}

build_review_backend_args() {
  REVIEW_BACKEND_ARGS=()
  case "$REVIEW_REVIEWER" in
    claude)
      [[ -n "$REVIEW_MODEL" ]]  && REVIEW_BACKEND_ARGS+=(--model "$REVIEW_MODEL")
      [[ -n "$REVIEW_EFFORT" ]] && REVIEW_BACKEND_ARGS+=(--effort "$REVIEW_EFFORT")
      ;;
    codex)
      [[ -n "$REVIEW_MODEL" ]]  && REVIEW_BACKEND_ARGS+=(--model "$REVIEW_MODEL")
      [[ -n "$REVIEW_EFFORT" ]] && REVIEW_BACKEND_ARGS+=(-c "model_reasoning_effort=${REVIEW_EFFORT}")
      ;;
  esac
  return 0
}

review_config_summary() {
  printf 'model=%s effort=%s' "${REVIEW_MODEL:-inherit}" "${REVIEW_EFFORT:-inherit}"
}

review_take_effort() {
  local tag="$1" value="$2" vocab ok=0 e
  vocab="$(review_effort_vocab "$REVIEW_REVIEWER")"
  for e in $vocab; do
    [[ "$e" == "$value" ]] && ok=1
  done
  if [[ "$ok" -ne 1 ]]; then
    echo "[${tag}] unsupported ${REVIEW_REVIEWER} effort '${value}' (--effort) — expected one of: ${vocab// /, }. Refusing to launch the reviewer." >&2
    exit 2
  fi
  REVIEW_EFFORT="$value"
}
