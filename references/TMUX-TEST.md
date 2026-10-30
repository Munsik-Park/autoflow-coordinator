# tmux 조율 시험 — cmux 조작의 tmux 대응 확인

작성: 2026-10-22. 환경: tmux 3.8, Claude Code 2.1.308, macOS(Darwin 25.6.0), 창 252×49. 머신 로컬 자료다.

목적: 조율 세션과 `tools/`가 cmux로 하는 조작(화면 분할, 칸 생성, 세션 생성, 메시지 전달, 화면 판독)을 tmux로 할 수 있는지 확인한다. 근거는 tmux man page와 아래 실측이다. 시험 세션은 `--model haiku`로 띄웠고, 시험이 끝난 뒤 칸·session·claude 프로세스를 모두 정리했다.

## 1. 환경 판별

| 항목 | tmux 안 | cmux 안 |
|---|---|---|
| `$TMUX` | 값 있음 (`/private/tmp/tmux-501/default,…`) | — |
| `$TMUX_PANE` | 값 있음 (`%0`) | — |
| `$TERM_PROGRAM` | `tmux` | — |
| `CMUX_*` 환경변수 | 없음 | 있음 (`CMUX_SURFACE_ID` 등, cmux hook settings에서 참조) |

판별은 `[ -n "$TMUX" ]`(tmux)와 `CMUX_*` 존재(cmux)로 한다. 이 tmux 세션에서는 `cmux`가 PATH에 없었다.

## 2. 대응표 (모두 실측)

| 용도 | cmux | tmux | 결과 |
|---|---|---|---|
| 자기 칸 확인 | `identify` (`caller.surface_ref`) | `$TMUX_PANE` | ✅ |
| 칸 분할 | `new-split right/down --focus false` | `split-window -d -h/-v -t <pane> -c <dir> -P -F '#{pane_id}'` | ✅ 새 pane id를 돌려준다 |
| 균등 분배 | `rpc workspace.equalize_splits` | 행 분할 전에 `select-layout -t <win> even-horizontal` | ✅ |
| 폭 지정 | `resize-pane --amount <px>` | `resize-pane -t <pane> -x <cols>` (단위는 cell) | ✅ 조율 83, 작업 40–41 cols |
| tab 이름 | `rename-tab` | `set -p -t <pane> @label "S1 …"`, `set -w pane-border-status top`, `set -w pane-border-format ' #{?#{@label},#{@label},#{pane_title}} '` | ✅ |
| 전체 칸 목록 | `tree --all`, `rpc pane.list` | `list-panes -a -F '…'` (`-s`는 session 단위) | ✅ |
| 명령 입력 | `send` | `send-keys -t <pane> -l "<text>"` 다음 `send-keys -t <pane> Enter` | ✅ 분할 직후 바로 보내도 도착 |
| 화면 판독 | `read-screen --lines 12` | `capture-pane -p -t <pane>` | ✅ |
| 추가 지시 | `paste --submit - < file` | `load-buffer -b <buf> <file>` → `paste-buffer -r -d -b <buf> -t <pane>` → `send-keys Enter` | ✅ (§3.2) |
| 특수 키 | — | `send-keys -t <pane> Escape` / `Down` / `Enter` | ✅ |
| 칸 닫기 | `close-surface` (탭 전체 닫기 확인 창, 사용 금지) | `kill-pane -t <pane>` | ✅ 그 칸만 닫힌다 |
| 세션 간 메시지 | `SendMessage` | 같음 | ✅ ListAgents에 `tmux 0:@0.%18`로 표시 |

## 3. 시험 내용

### 3.1 배치

```bash
CO=<checkout>; C=$TMUX_PANE; T=$(tmux display -p -t $C '#{session_name}:#{window_index}')
sp(){ tmux split-window -d $1 -t $2 -c $CO -P -F '#{pane_id}'; }
S1=$(sp -h $C); S2=$(sp -h $S1); S3=$(sp -h $S2); S4=$(sp -h $S3)
tmux select-layout -t $T even-horizontal
S5=$(sp -v $S1); S6=$(sp -v $S2); S7=$(sp -v $S3)
W=$(tmux display -p -t $T '#{window_width}'); WK=$(( (W - 83 - 4) / 4 ))
tmux resize-pane -t $C -x 83; for p in $S1 $S2 $S3; do tmux resize-pane -t $p -x $WK; done
```

결과(252 cols): 조율 83×49, S1–S3·S5–S7 41×24, S4 42×49. layout 폭 합 252로 창과 일치했다.

### 3.2 세션 생성과 메시지 전달

| 시험 | 방법 | transcript 결과 |
|---|---|---|
| 첫 지시 (3줄, `"…"`, `$HOME` 포함) | `send-keys -l 'claude --model haiku --session-id <id> "$(cat prompt.txt)"'` + Enter | 원문 그대로 user 메시지, 응답 `PONG-1` |
| 추가 지시, bracketed paste | `paste-buffer -p` | `<pasted_content id=…>`로 감싸져 도착, 응답 `PONG-2 3` |
| 추가 지시, bracket 없음 | `paste-buffer -r` (LF 유지) | 일반 user 메시지 하나로 도착, 응답 `PONG-3 2` |
| 긴 지시 (81줄, 3959 bytes) | `paste-buffer -r` + 1초 뒤 Enter | 한 메시지로 도착, 응답 `PONG-4 79`. 차이는 tab → 공백 4칸뿐 |
| `/usage` 화면 | `send-keys -l '/usage'` + Enter, 판독 후 `Escape` | 열림·닫힘 확인, 프롬프트 복귀 |
| workspace trust 창 | 처음 쓰는 폴더에서 claude 실행 | `capture-pane` 내용이 `watch.py`의 `INPUT_RE`(`Esc to cancel`, `❯ …`)에 일치. `Escape` → claude 종료 |

### 3.3 기존 도구

- **`tools/watch.py` 판정:** 시험 run dir(`run.env`, `sessions.tsv`에 pane id 기록)로 `watch.py <run> 1 0 150`을 실행하자 `TURN_END 1`이 나왔다. transcript 기반 판정은 터미널에 의존하지 않는다.
- **세션 간 메시지:** tmux 칸에서 띄운 claude는 ListAgents에 `tmux 0:@0.%18`로 표시됐다.

## 4. 주의점

1. **`select-layout -E` 금지:** 열과 행이 섞인 배치에 쓰면 layout 폭 합이 363으로 창 폭 252를 넘었고, 마지막 열이 화면 밖으로 밀렸다. 이후 `resize-pane`으로도 복구되지 않았다. §3.1의 순서(`even-horizontal`, 행 분할, `resize-pane -x`)만 정상이었다.
2. **`paste-buffer -p` 금지:** Claude Code가 bracketed paste를 `<pasted_content>`로 감싸서, 지시가 붙여넣은 자료로 전달된다. `-r`을 쓴다. `-p`도 `-r`도 없으면 LF가 CR로 바뀌어 줄마다 제출될 수 있다(man page `paste-buffer`).
3. **`-t` 없는 `tmux display -p` 금지:** 호출한 칸이 아니라 활성 칸을 돌려준다(%10에서 실행해 %9가 나왔다). 자기 칸은 `$TMUX_PANE`으로 확인한다.
4. **칸 제목 대신 `@label`:** `allow-set-title on`이라 claude가 pane title을 바꾼다(`✳ <세션 제목>`). `select-pane -T`로 붙인 이름은 덮어쓰이므로 이름표는 `@label`과 `pane-border-format`으로 붙인다.
5. **Enter는 따로 보낸다:** `send-keys -l`이나 `paste-buffer` 뒤에 `send-keys Enter`를 별도로 보낸다. 긴 paste는 0.5–1초 쉬고 보냈다.

## 5. 현재 도구가 tmux에서 깨지는 곳

| 위치 | 문제 | 근거 |
|---|---|---|
| `tools/launch.sh:14,19` | `cmux send`, `cmux read-screen`을 직접 호출한다 | cmux가 없는 환경에서는 실패한다 |
| `tools/watch.py` `screen_waiting()` (98행) | cmux 호출이 예외가 나면 `False`를 돌려줘서 `WAITING_INPUT`이 영영 나오지 않는다. 오류도 나지 않는다 | 코드상 `except Exception: return False` |
| `tools/watch.py` `live_children()`, `tools/check.sh:41` | `.local/bin/claude` 패턴이 tmux에서 띄운 claude를 잡지 못한다 | tmux 칸의 프로세스 명령은 `claude --model haiku …`였다. cmux는 `~/.local/bin/claude --settings ~/.cmuxterm/claude-settings/….json …`로 띄운다. `$HOME/.local/bin/claude`로 띄우면 `pgrep -f '\.local/bin/claude'`에 잡히는 것을 확인했다 |
| cmux hooks | cmux가 `--settings`로 넣는 Notification hook(`cmux hooks claude …`)이 tmux에는 없다 | 도구들이 이 hook에 의존하지 않아 영향은 없다 |

## 6. tmux 기본 조작 (운영자용)

| 동작 | 키 / 명령 |
|---|---|
| 칸 이동 | `Ctrl-b` 다음 방향키 |
| 한 칸 크게 보기와 되돌리기 | `Ctrl-b` 다음 `z` |
| 지난 출력 스크롤 | `Ctrl-b` 다음 `[`, 끝낼 때 `q` |
| session 목록에서 전환 | `Ctrl-b` 다음 `s` |
| 다른 터미널에서 session 보기 | `tmux attach -t <session>` |
| 마우스로 칸 선택과 스크롤 | `tmux set -g mouse on` |
| detach (화면에서 빠져나감, 주의) | `Ctrl-b` 다음 `d` |
