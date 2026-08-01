#!/usr/bin/env bash
# Install / update / uninstall a systemd --user unit for mention-scout watch.
# MS-0008: packaging only. Does not place trades or send email.
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

UNIT_NAME="mention-scout-watch.service"
TEMPLATE_REL="deploy/systemd/mention-scout-watch.service"
EMAIL_MODE="on" # on | off
DO_ENABLE=0
DO_START=0
DO_DISABLE=0
DO_UNINSTALL=0
DRY_RUN=0
STRICT=0
POLL_SECONDS=""
WORKING_DIRECTORY=""
PYTHON_BIN=""
EXTRA_ARGS=""
REPO_ROOT="${DEFAULT_REPO_ROOT}"
ENABLE_LINGER=0

usage() {
  cat <<'EOF'
Usage: scripts/install-user-service.sh [options]

Install or manage a systemd --user unit for long-running mention-scout watch.

Options:
  --email              Include --email-new in ExecStart (default)
  --no-email           Watch only (--watch-new)
  --enable             systemctl --user enable <unit>
  --start / --now      systemctl --user start <unit>
  --enable-now         enable + start
  --disable            disable unit (keep installed file)
  --uninstall          disable --now, remove unit file, daemon-reload
  --dry-run            Print actions and rendered unit; no writes/start
  --strict             Fail email preflight if swaks/password missing or mode unsafe
  --poll-seconds N     Bake --poll-seconds N into ExecStart (app default 300 if omitted)
  --working-directory PATH
                       Override WorkingDirectory (default: repo checkout root)
  --python PATH        Absolute python interpreter (default: command -v python3)
  --unit-name NAME     Unit filename (default: mention-scout-watch.service)
  --extra-args "..."   Append extra CLI args to ExecStart (trusted escape hatch)
  --repo-root PATH     Override repo root detection
  --enable-linger      Run loginctl enable-linger for the current user (explicit opt-in)
  -h, --help           Show this help

Notes:
  - User systemd only (~/.config/systemd/user or $XDG_CONFIG_HOME/systemd/user).
  - Does not auto-enable linger unless --enable-linger is passed.
  - Never prints password file contents.
  - Re-run after moving the checkout so paths stay correct.
EOF
}

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

warn() {
  printf 'WARNING: %s\n' "$*" >&2
}

info() {
  printf '%s\n' "$*"
}

is_abs_path() {
  [[ "${1:-}" == /* ]]
}

require_positive_int() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "${name} must be a positive integer (got: ${value})"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --email)
      EMAIL_MODE="on"
      shift
      ;;
    --no-email)
      EMAIL_MODE="off"
      shift
      ;;
    --enable)
      DO_ENABLE=1
      shift
      ;;
    --start|--now)
      DO_START=1
      shift
      ;;
    --enable-now)
      DO_ENABLE=1
      DO_START=1
      shift
      ;;
    --disable)
      DO_DISABLE=1
      shift
      ;;
    --uninstall)
      DO_UNINSTALL=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    --poll-seconds)
      [[ $# -ge 2 ]] || die "--poll-seconds requires a value"
      POLL_SECONDS="$2"
      require_positive_int "--poll-seconds" "$POLL_SECONDS"
      shift 2
      ;;
    --working-directory)
      [[ $# -ge 2 ]] || die "--working-directory requires a path"
      WORKING_DIRECTORY="$2"
      shift 2
      ;;
    --python)
      [[ $# -ge 2 ]] || die "--python requires a path"
      PYTHON_BIN="$2"
      shift 2
      ;;
    --unit-name)
      [[ $# -ge 2 ]] || die "--unit-name requires a name"
      UNIT_NAME="$2"
      shift 2
      ;;
    --extra-args)
      [[ $# -ge 2 ]] || die "--extra-args requires a value"
      EXTRA_ARGS="$2"
      shift 2
      ;;
    --repo-root)
      [[ $# -ge 2 ]] || die "--repo-root requires a path"
      REPO_ROOT="$2"
      shift 2
      ;;
    --enable-linger)
      ENABLE_LINGER=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1 (try --help)"
      ;;
  esac
done

# Mutual exclusion for lifecycle modes
mode_count=0
[[ "$DO_UNINSTALL" -eq 1 ]] && mode_count=$((mode_count + 1))
[[ "$DO_DISABLE" -eq 1 ]] && mode_count=$((mode_count + 1))
# install/update is implied when neither uninstall nor disable-only
if [[ "$mode_count" -gt 1 ]]; then
  die "Use only one of --disable or --uninstall"
fi
if [[ "$DO_UNINSTALL" -eq 1 && ( "$DO_ENABLE" -eq 1 || "$DO_START" -eq 1 ) ]]; then
  die "--uninstall cannot be combined with --enable/--start/--enable-now"
fi
if [[ "$DO_DISABLE" -eq 1 && ( "$DO_ENABLE" -eq 1 || "$DO_START" -eq 1 ) ]]; then
  die "--disable cannot be combined with --enable/--start/--enable-now"
fi

# Resolve repo root
if [[ ! -d "$REPO_ROOT" ]]; then
  die "Repo root is not a directory: $REPO_ROOT"
fi
REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"

ENTRY_PATH="${REPO_ROOT}/mention_scout.py"
TEMPLATE_PATH="${REPO_ROOT}/${TEMPLATE_REL}"

if [[ ! -e "$ENTRY_PATH" && ! -L "$ENTRY_PATH" ]]; then
  die "Stable entry not found: $ENTRY_PATH"
fi
# Keep stable entry basename (symlink OK). Do not resolve to kalshi_mention_scout.py.
ENTRY_PATH="${REPO_ROOT}/mention_scout.py"

if [[ -z "$WORKING_DIRECTORY" ]]; then
  WORKING_DIRECTORY="$REPO_ROOT"
fi
if [[ ! -d "$WORKING_DIRECTORY" ]]; then
  die "WorkingDirectory is not a directory: $WORKING_DIRECTORY"
fi
WORKING_DIRECTORY="$(cd "$WORKING_DIRECTORY" && pwd)"

if [[ -z "$PYTHON_BIN" ]]; then
  if ! PYTHON_BIN="$(command -v python3 2>/dev/null)"; then
    die "python3 not found on PATH; pass --python /path/to/python"
  fi
fi
# Prefer absolute path for systemd ExecStart
if ! is_abs_path "$PYTHON_BIN"; then
  if resolved_py="$(command -v "$PYTHON_BIN" 2>/dev/null)"; then
    PYTHON_BIN="$resolved_py"
  fi
fi
if is_abs_path "$PYTHON_BIN"; then
  PYTHON_BIN="$(readlink -f "$PYTHON_BIN")"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  die "Python interpreter is not executable: $PYTHON_BIN"
fi

case "$UNIT_NAME" in
  *.service) ;;
  *) UNIT_NAME="${UNIT_NAME}.service" ;;
esac
# Keep unit names simple (no path components)
if [[ "$UNIT_NAME" == */* || "$UNIT_NAME" == *".."* ]]; then
  die "Invalid --unit-name: $UNIT_NAME"
fi

XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
UNIT_DIR="${XDG_CONFIG_HOME}/systemd/user"
UNIT_PATH="${UNIT_DIR}/${UNIT_NAME}"

PASSWORD_FILE="${HOME}/.config/.google-password"

shell_join_exec() {
  # Produce a single ExecStart line with shell-safe quoting.
  local out="" part
  for part in "$@"; do
    if [[ -z "$out" ]]; then
      out="$(printf '%q' "$part")"
    else
      out+=" $(printf '%q' "$part")"
    fi
  done
  printf '%s' "$out"
}

build_exec_start() {
  local -a cmd=("$PYTHON_BIN" "$ENTRY_PATH" "--watch-new")
  if [[ "$EMAIL_MODE" == "on" ]]; then
    cmd+=("--email-new")
  fi
  if [[ -n "$POLL_SECONDS" ]]; then
    cmd+=("--poll-seconds" "$POLL_SECONDS")
  fi
  if [[ -n "$EXTRA_ARGS" ]]; then
    # Intentionally unquoted split for trusted installer escape hatch.
    # shellcheck disable=SC2206
    local -a extra=( $EXTRA_ARGS )
    cmd+=("${extra[@]}")
  fi
  shell_join_exec "${cmd[@]}"
}

render_unit() {
  local exec_start="$1"
  if [[ ! -f "$TEMPLATE_PATH" ]]; then
    die "Unit template not found: $TEMPLATE_PATH"
  fi
  local line out=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      Documentation=file://@REPO_ROOT@/README.md)
        line="Documentation=file://${REPO_ROOT}/README.md"
        ;;
      WorkingDirectory=@REPO_ROOT@)
        line="WorkingDirectory=${WORKING_DIRECTORY}"
        ;;
      ExecStart=*)
        line="ExecStart=${exec_start}"
        ;;
      *)
        line="${line//@PYTHON@/${PYTHON_BIN}}"
        line="${line//@ENTRY@/${ENTRY_PATH}}"
        line="${line//@REPO_ROOT@/${REPO_ROOT}}"
        ;;
    esac
    out+="${line}"$'\n'
  done <"$TEMPLATE_PATH"
  if grep -qE '@[A-Z_]+@' <<<"$out"; then
    die "Rendered unit still contains unresolved placeholders"
  fi
  printf '%s' "$out"
}

email_preflight() {
  [[ "$EMAIL_MODE" == "on" ]] || return 0
  local issues=0

  if ! command -v swaks >/dev/null 2>&1; then
    msg="swaks not found on PATH (required for --email-new under systemd)"
    if [[ "$STRICT" -eq 1 ]]; then
      die "$msg (strict)"
    fi
    warn "$msg"
    issues=1
  fi

  if [[ ! -f "$PASSWORD_FILE" ]]; then
    msg="password file missing: ${PASSWORD_FILE} (app default for --email-new)"
    if [[ "$STRICT" -eq 1 ]]; then
      die "$msg (strict)"
    fi
    warn "$msg"
    issues=1
  else
    # Mode check only — never read or print contents
    local mode
    mode="$(stat -c '%a' "$PASSWORD_FILE" 2>/dev/null || stat -f '%OLp' "$PASSWORD_FILE" 2>/dev/null || echo "")"
    if [[ -n "$mode" ]]; then
      # Fail if group/other have any permission bits (mirror app expectations)
      local last2="${mode: -2}"
      if [[ "$last2" != "00" ]]; then
        msg="password file mode is ${mode}; expected not group/other-readable (chmod 600 ${PASSWORD_FILE})"
        if [[ "$STRICT" -eq 1 ]]; then
          die "$msg (strict)"
        fi
        warn "$msg"
        issues=1
      fi
    fi
  fi

  return 0
}

systemctl_user() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[dry-run] systemctl --user $*"
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    die "systemctl not found; cannot manage user units (try --dry-run)"
  fi
  systemctl --user "$@"
}

maybe_hint_linger() {
  if [[ "$ENABLE_LINGER" -eq 1 ]]; then
    return 0
  fi
  if ! command -v loginctl >/dev/null 2>&1; then
    info "Note: for boot without interactive login, run: loginctl enable-linger \"\$USER\""
    return 0
  fi
  local user linger
  user="$(id -un)"
  linger="$(loginctl show-user "$user" -p Linger --value 2>/dev/null || true)"
  if [[ "${linger,,}" != "yes" ]]; then
    info "Note: linger is not enabled for ${user}. User units may not start at boot without login."
    info "      To enable manually: loginctl enable-linger ${user}"
  fi
}

do_enable_linger() {
  if [[ "$ENABLE_LINGER" -ne 1 ]]; then
    return 0
  fi
  local user
  user="$(id -un)"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[dry-run] loginctl enable-linger ${user}"
    return 0
  fi
  if ! command -v loginctl >/dev/null 2>&1; then
    die "loginctl not found; cannot --enable-linger"
  fi
  loginctl enable-linger "$user"
  info "Enabled linger for ${user}"
}

print_summary() {
  info "Unit name:          ${UNIT_NAME}"
  info "Unit path:          ${UNIT_PATH}"
  info "Repo root:          ${REPO_ROOT}"
  info "WorkingDirectory:   ${WORKING_DIRECTORY}"
  info "Python:             ${PYTHON_BIN}"
  info "Entry:              ${ENTRY_PATH}"
  info "Email in unit:      ${EMAIL_MODE}"
  info "Cache/queue note:   relative paths resolve under WorkingDirectory"
}

# --- main actions ---

if [[ "$DO_UNINSTALL" -eq 1 ]]; then
  print_summary
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[dry-run] would disable --now and remove ${UNIT_PATH}"
    systemctl_user daemon-reload
    exit 0
  fi
  # Ignore failures if unit not loaded/enabled
  systemctl --user disable --now "$UNIT_NAME" >/dev/null 2>&1 || true
  if [[ -e "$UNIT_PATH" ]]; then
    rm -f "$UNIT_PATH"
    info "Removed ${UNIT_PATH}"
  else
    info "Unit file already absent: ${UNIT_PATH}"
  fi
  systemctl_user daemon-reload
  info "Uninstall complete."
  exit 0
fi

if [[ "$DO_DISABLE" -eq 1 ]]; then
  print_summary
  systemctl_user disable "$UNIT_NAME"
  info "Disabled ${UNIT_NAME} (unit file kept at ${UNIT_PATH})"
  exit 0
fi

# Install / update path
[[ -f "$TEMPLATE_PATH" ]] || die "Unit template not found: $TEMPLATE_PATH"
email_preflight
EXEC_START="$(build_exec_start)"
RENDERED="$(render_unit "$EXEC_START")"

print_summary
info "ExecStart:          ${EXEC_START}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  info "----- rendered unit (dry-run) -----"
  printf '%s\n' "$RENDERED"
  info "----- end rendered unit -----"
  info "[dry-run] would write ${UNIT_PATH}"
  info "[dry-run] would run: systemctl --user daemon-reload"
  [[ "$DO_ENABLE" -eq 1 ]] && info "[dry-run] would run: systemctl --user enable ${UNIT_NAME}"
  [[ "$DO_START" -eq 1 ]] && info "[dry-run] would run: systemctl --user start ${UNIT_NAME}"
  do_enable_linger
  maybe_hint_linger
  exit 0
fi

mkdir -p "$UNIT_DIR" || die "Cannot create unit directory: $UNIT_DIR"
# Atomic-ish write
tmp_unit="$(mktemp "${UNIT_DIR}/.${UNIT_NAME}.XXXXXX")"
printf '%s\n' "$RENDERED" >"$tmp_unit"
mv -f "$tmp_unit" "$UNIT_PATH"
info "Wrote ${UNIT_PATH}"

systemctl_user daemon-reload

if [[ "$DO_ENABLE" -eq 1 ]]; then
  systemctl_user enable "$UNIT_NAME"
  info "Enabled ${UNIT_NAME}"
fi
if [[ "$DO_START" -eq 1 ]]; then
  systemctl_user start "$UNIT_NAME"
  info "Started ${UNIT_NAME}"
fi

do_enable_linger
maybe_hint_linger

info "Done. Logs: journalctl --user -u ${UNIT_NAME} -f"
info "Status: systemctl --user status ${UNIT_NAME}"
