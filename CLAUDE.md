# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

Discord Gateway Botとして常駐し、ユーザーからのメッセージをトリガーに **Agent Client Protocol (ACP)** を通じてAIエージェント（Claude Code等）と対話できるようにするアプリケーション。

### 提供価値
- DiscordからシームレスにAIエージェントと対話できる
- モバイルからでもエージェントを操作できる

### 設計方針
- ACP ClientとしてBotを実装し、ACP Server（claude-code-acp等）と通信
- Discord側のメッセージに応じてACP Serverへ問い合わせ
- AIエージェント（Claude Code等）のCLIの標準入出力を直接ハックしない（ACPで抽象化）
- 疎結合でシンプルな構成

### 主要なドキュメント
- `.local/Proposal.md`: プロジェクト提案書
- `.local/Design.md`: 詳細設計仕様書
- `.local/ADR.md`: アーキテクチャ決定記録
- [Agent Client Protocol 仕様](https://agentclientprotocol.com/)

## 技術スタック

- **Python**: 3.12 以上が必須（現在は 3.14 で開発中）
- **パッケージマネージャ**: uv (uv.lock で依存関係を管理)
- **Discord**: discord.py v2.x
- **ACP**: agent-client-protocol (PyPI)
- **バリデーション**: Pydantic v2.x, pydantic-settings
- **環境変数**: python-dotenv
- **リンター/フォーマッター**: Ruff
- **型チェック**: mypy
- **テストフレームワーク**: pytest, pytest-asyncio

## アーキテクチャ

### 3層アーキテクチャ

```
┌─────────────────────────────────────────────────────────┐
│                  Presentation Layer                     │
│         (Discord Bot / Commands / Events)               │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                  Application Layer                      │
│      (Session / Project / Conversation Services)        │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│                 Infrastructure Layer                    │
│            (ACP Client / Config / Storage)              │
└─────────────────────────────────────────────────────────┘
```

### プロジェクト構成（予定）

```
discord-acp-bridge/
├── src/
│   └── discord_acp_bridge/
│       ├── __init__.py
│       ├── main.py                 # エントリポイント
│       ├── presentation/
│       │   ├── __init__.py
│       │   ├── bot.py              # Discord Bot Client
│       │   ├── commands/           # Slash Commands (Cog)
│       │   │   ├── __init__.py
│       │   │   ├── project.py      # /project list, /project switch
│       │   │   └── agent.py        # /agent start, /agent stop, /agent kill, /agent status
│       │   └── events/             # Event Handlers
│       │       ├── __init__.py
│       │       └── message.py      # on_message
│       ├── application/
│       │   ├── __init__.py
│       │   ├── session.py          # セッション管理（Session Service）
│       │   ├── project.py          # プロジェクト管理（Project Service）
│       │   └── conversation.py     # 会話制御
│       └── infrastructure/
│           ├── __init__.py
│           ├── acp_client.py       # ACP Client Wrapper
│           ├── config.py           # 設定管理
│           └── storage.py          # 永続化（将来用）
├── tests/
│   ├── __init__.py
│   ├── test_session.py
│   └── test_acp_client.py
├── pyproject.toml
├── .env.example
└── README.md
```

### 主要コンポーネント

| コンポーネント | 責務 | 依存先 |
|---------------|------|--------|
| Discord Bot | Gateway接続、イベントディスパッチ | discord.py |
| Slash Commands | コマンド受付、入力検証、応答整形 | Session Service, Project Service |
| Event Handlers | メッセージイベント処理 | Session Service |
| Session Service | セッションライフサイクル管理、プロンプト送受信 | ACP Client |
| Project Service | プロジェクト自動スキャン・取得・切り替え | Config |
| ACP Client | ACPプロトコル通信、プロセス管理 | Config |
| Config | 設定値の読み込み・提供 | 環境変数, .env |

### 通信フロー

1. ユーザーがDiscordでコマンドまたはメッセージを送信
2. Discord Bot（Presentation Layer）がイベントを受信
3. Session Service（Application Layer）が処理
4. ACP Client（Infrastructure Layer）がJSON-RPC over stdioでACP Serverと通信
5. ACP Serverがストリーミングで応答を返す
6. Discord Botがメッセージを整形してDiscordに送信

## 主要機能

### MVP（最小限の機能）
- Discord Bot基盤（Gateway接続、メッセージ送受信）
- プロジェクト切り替え機能
- 基本的なメッセージのやり取り

### Discord Slash Commands

| コマンド | 説明 | 引数 |
|---------|------|------|
| `/project list` | Trusted Path配下のプロジェクト一覧を表示 | なし |
| `/project switch` | 操作対象プロジェクトを切り替え | `id` (integer): プロジェクトID |
| `/agent start` | エージェントセッションを開始 | なし |
| `/agent stop` | エージェントセッションを正常終了 | なし |
| `/agent kill` | エージェントセッションを強制終了 | なし |
| `/agent status` | 現在のセッション状態を表示 | なし |

### プロジェクト管理
- プロジェクトは `TRUSTED_PATHS` 環境変数で指定されたディレクトリ配下のディレクトリを自動スキャンして検出される
- 隠しディレクトリ（`.` で始まるディレクトリ）は自動的に除外される
- プロジェクトIDは自動スキャン結果のパス名順に割り当てられる（1から連番）
- Trusted Path配下にないパスへのアクセスは拒否される

### セッション管理
- セッションはプロジェクトに紐づく
- セッション開始時に専用のDiscordスレッドを作成
- スレッド内のメッセージが自動的にエージェントに送信される
- 30分間無応答の場合、自動的に強制終了（Watchdog Timer）

### データモデル

#### Session
- `id`: セッション識別子（UUID）
- `user_id`: Discordユーザー ID
- `project`: 紐づくプロジェクト
- `state`: 現在の状態（Created / Active / Prompting / Closed）
- `thread_id`: DiscordスレッドID
- `acp_session_id`: ACPセッションID
- `created_at`: 作成日時
- `last_activity_at`: 最終応答日時

#### Project
- `id`: プロジェクトID（1から連番）
- `path`: ディレクトリパス
- `is_active`: アクティブ状態

## 開発コマンド

### セットアップ
```bash
uv sync  # 依存関係のインストール
```

### アプリケーションの実行
```bash
python main.py
# または python -m discord_acp_bridge
```

### リンティングとフォーマット
```bash
ruff check .          # Ruff によるリンティング
ruff format .         # Ruff によるフォーマット (自動修正)
```

### 型チェック
```bash
mypy .                # mypy による型チェック
```

### テスト
```bash
pytest                # 全テストを実行
pytest path/to/test   # 特定のテストを実行
```

## コーディング規約

### Ruff 設定 (.ruff.toml)
- **行の長さ**: 88 文字
- **ターゲット Python バージョン**: 3.10+
- **自動修正**: 有効 (fix = true)
- **有効なルールセット**:
  - flake8-comprehensions (C4)
  - flake8-bugbear (B)
  - pycodestyle (E, W)
  - pyflakes (F)
  - flake8-future-annotations (FA)
  - flynt (FLY)
  - refurb (FURB)
  - flake8-logging-format (G)
  - isort (I)
  - flake8-implicit-str-concat (ISC)
  - flake8-logging (LOG)
  - perflint (PERF)
  - pygrep-hooks (PGH)
  - flake8-pytest-style (PT)
  - flake8-type-checking (TCH)
  - pyupgrade (UP)
  - flake8-2020 (YTT)
- **除外ルール**: E501 (行の長さエラーは自動フォーマッティングに任せる)
- **引用符スタイル**: preserve (既存のスタイルを維持)
- **docstring コードフォーマット**: 有効

### 依存関係の管理
- 本番環境の依存関係は `dependencies` セクションに追加
- 開発環境の依存関係は `dependency-groups.dev` セクションに追加
- 依存関係を追加した後は `uv lock` を実行して uv.lock を更新

## 設定

### 環境変数

プロジェクトルートに `.env` ファイルを作成して以下の設定を行う：

| キー | 型 | 必須 | デフォルト | 説明 |
|------|-----|------|-----------|------|
| `DISCORD_BOT_TOKEN` | string | Yes | - | Discord Bot Token |
| `DISCORD_GUILD_ID` | integer | Yes | - | 開発用ギルドID（指定時はそのギルドのみにコマンド同期） |
| `DISCORD_ALLOWED_USER_ID` | integer | Yes | - | 利用を許可するDiscordユーザーID |
| `AGENT_COMMAND` | list[string] | No | ["claude-code-acp"] | ACP Server起動コマンド |
| `TRUSTED_PATHS` | list[string] | Yes | [] | プロジェクトとして許可するディレクトリのルートパスのリスト（JSON配列形式） |

**注意**: `AGENT_COMMAND` と `TRUSTED_PATHS` は JSON 配列形式で指定します（例: `["path1", "path2"]`）。

## ACP通信

### 通信方式
- MVP: stdio経由のJSON-RPC（`acp.transports.StdioTransport`）
- 将来: WebSocket（`acp.transports.WebSocketTransport`）

### 主要なACPメソッド

| メソッド | 方向 | 目的 | 入力 | 出力 |
|---------|------|------|------|------|
| `initialize` | Client → Server | クライアント情報と機能の通知 | client_info, capabilities | サーバー機能情報 |
| `session/new` | Client → Server | 新規セッションの確立 | working_directory | session_id |
| `session/prompt` | Client → Server | ユーザー入力の送信 | session_id, content | なし（ストリーミング通知） |
| `session/update` | Server → Client | 応答のストリーミング配信 | update_type, content | - |
| `session/cancel` | Client → Server | セッションの終了要求 | session_id | なし |

### session/update の update_type

| type | 内容 | contentの構造 |
|------|------|---------------|
| `message_chunk` | テキスト応答の断片 | `{role, text}` |
| `tool_call` | ツール実行通知 | `{tool_call_id, name, status, input}` |
| `end_turn` | ターン終了 | `{stop_reason}` |

## 実装上の注意点

### Discord API制約
- メッセージは2000文字制限があるため、長文は分割して送信する
- コードブロック内で分割する場合、ブロックを壊さないよう注意
- 応答待機中は「入力中...」を表示（タイピングインジケーター）

### セキュリティ
- Bot Tokenは環境変数で管理し、.gitignoreに.envを追加
- `DISCORD_ALLOWED_USER_ID` に一致するユーザーのみ操作可能
- 許可外ユーザーからの操作は無視（応答しない）
- 登録済みプロジェクトパスのみアクセス許可

### エラー処理
- 認証エラー: 通知しない（無視）、ログ記録（WARN）
- 入力エラー: 具体的なエラーメッセージ、ログ記録（INFO）
- 状態エラー: 操作手順の案内、ログ記録（WARN）
- 接続エラー: 汎用エラーメッセージ、ログ記録（ERROR）、リトライなし
- 内部エラー: 「エラーが発生しました」、ログ記録（ERROR）、スタックトレース

### Watchdog Timer
- 最大無応答時間: 30分
- `session/update` 通知が30分間ない場合、プロセスを自動kill
- ストリーミング中はupdate毎にタイマーをリセット
- 自動kill時はスレッドに「エージェントが応答しないため、セッションを強制終了しました」と通知

## 開発アプローチ

1. ACP Clientとして必要最低限のI/Fを整える
2. Discord Botと接続
3. 最小のMVPを構築
4. 実運用しながら改修

## 制約事項

| ID | 制約 | 理由 |
|----|------|------|
| C-1 | ACP通信はstdio経由のみ | MVP段階ではローカル実行を優先 |
| C-2 | 許可されたユーザーのみ利用可能 | 個人サーバー運用前提、セキュリティ確保 |
| C-3 | 同時アクティブセッションは1つ | 単一ユーザー運用のため |
| C-4 | Discordメッセージは2000文字制限 | Discord API制約 |

## スコープ外

- ACP Server側の実装（Claude Code + [claude-code-acp](https://github.com/zed-industries/claude-code-acp) での利用を想定）
- セッション履歴の永続化（MVP後に検討）
- ファイル添付の扱い（MVP後に検討）

## 参照リンク

- [Agent Client Protocol](https://agentclientprotocol.com/)
- [ACP Python SDK](https://github.com/agentclientprotocol/python-sdk)
- [ACP Python SDK Quick Start](https://agentclientprotocol.github.io/python-sdk/quickstart/)
- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [discord.py GitHub](https://github.com/Rapptz/discord.py)
