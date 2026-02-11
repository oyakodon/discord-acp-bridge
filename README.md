# discord-acp-bridge

## 概要

Discord Gateway Botとして常駐し、ユーザーからのメッセージをトリガーにAIエージェントと対話できるようにするアプリケーション。

- **Agent Client Protocol (ACP)** のClientとしてBotを実装
  - AIエージェント (Claude Codeなど)のCLIの標準入出力を直接ハックしない
- Discord側のメッセージに応じてACP Serverへ問い合わせ

## セットアップ

### 前提条件

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- ACP Server（例: [claude-code-acp](https://github.com/anthropics/claude-code)）

### 1. インストール

```bash
git clone https://github.com/oyakodon/discord-acp-bridge
cd discord-acp-bridge
uv sync
```

### 2. Discord Bot の作成

1. [Discord Developer Portal](https://discord.com/developers/applications) でアプリケーションを作成
2. **Bot** タブで Bot を有効化し、**Token** を取得
3. **OAuth2 → URL Generator** でスコープ `bot` + `applications.commands` を選択してサーバーに招待
   - またはクライアント ID を置き換えて以下の URL を使用:
   ```
   https://discord.com/oauth2/authorize?client_id=<<client_id>>&permissions=0&integration_type=0&scope=bot+applications.commands
   ```

### 3. 設定

`.env` ファイルをプロジェクトルートに作成:

```env
# 必須
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_GUILD_ID=123456789012345678
DISCORD_ALLOWED_USER_ID=123456789012345678
TRUSTED_PATHS=["path/to/your/projects"]

# 任意
AGENT_COMMAND=["claude-code-acp"]
PERMISSION_TIMEOUT=120.0
LOG_LEVEL=INFO
LOG_DIR=logs
```

> **Windows の場合:** npm でインストールされた `claude-code-acp` は `.cmd` スクリプトとして提供されるため、`AGENT_COMMAND` を以下のように設定してください。
>
> ```env
> AGENT_COMMAND=["cmd", "/c", "claude-code-acp"]
> ```

**ユーザー ID / ギルド ID の確認方法**: Discord の設定 → 詳細設定 → 開発者モードを有効にし、対象を右クリック → ID をコピー

設定項目の詳細は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) を参照。

### 4. 起動

```bash
uv run python -m discord_acp_bridge.main
```

## 使い方

Bot が起動したら、以下のスラッシュコマンドで操作します。

| コマンド | 説明 |
|---------|------|
| `/projects list` | 登録済みプロジェクト一覧を表示 |
| `/projects new <name>` | 新規プロジェクトディレクトリを作成 |
| `/agent start <project_id>` | エージェントセッションを開始（スレッドを自動作成） |
| `/agent stop` | セッションを正常終了 |
| `/agent kill` | セッションを強制終了 |
| `/agent status` | セッション状態を表示 |
| `/agent model <model_id>` | モデルを切り替え |
| `/agent usage` | 使用量情報を表示 |

セッション開始後は作成されたスレッドにメッセージを送ることでエージェントと対話できます。
