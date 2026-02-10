# CLAUDE.md

ユーザーへの回答は常に日本語で行うこと。

## プロジェクト概要

Discord Gateway Bot として常駐し、**Agent Client Protocol (ACP)** を通じて AI エージェントと対話するアプリケーション。
詳細な設計・アーキテクチャは **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** を参照。

## 開発コマンド

```bash
uv sync                    # 依存関係のインストール
uv run python -m discord_acp_bridge.main  # アプリケーションの実行
uv run pytest              # テスト実行
uv run mypy src tests      # 型チェック
uv run ruff check .        # リンティング
uv run ruff format .       # フォーマット
```

品質チェック:
```bash
uv run pytest && uv run mypy src tests && uv run ruff check .
```

## プロジェクト構成

```
src/discord_acp_bridge/
├── main.py                       # エントリポイント、Graceful Shutdown
├── presentation/                 # Presentation Layer
│   ├── bot.py                    #   Discord Bot Client
│   ├── commands/
│   │   ├── agent.py              #   /agent コマンド群
│   │   └── project.py            #   /projects コマンド群
│   ├── events/
│   │   └── message.py            #   スレッド内メッセージ処理
│   └── views/
│       └── permission.py         #   パーミッション要求 UI
├── application/                  # Application Layer
│   ├── session.py                #   セッション管理
│   ├── project.py                #   プロジェクト管理
│   └── models.py                 #   層間通信用データクラス
└── infrastructure/               # Infrastructure Layer
    ├── acp_client.py             #   ACP Client Wrapper
    ├── config.py                 #   Pydantic Settings 設定管理
    └── logging.py                #   structlog 構造化ログ
```

## コーディング規約

### Ruff (.ruff.toml)
- 行の長さ: 88 文字、ターゲット: py310
- 引用符スタイル: preserve（既存のスタイルを維持）
- 有効ルール: C4, B, E, F, FA, FLY, FURB, G, I, ISC, LOG, PERF, PGH, PT, TCH, UP, W, YTT
- 除外ルール: E501（自動フォーマッタに委譲）, TC002（型ヒントの実行時インポート許可）

### テスト
- 非同期テストは `@pytest.mark.asyncio` を使用
- モックは `unittest.mock` の `AsyncMock`, `MagicMock` を活用
- 異常系テストも含める

### Pydantic
- フィールド型は実行時にも必要なため `TYPE_CHECKING` ブロックに入れない
- 必要に応じて `# noqa: TC001` で Ruff ルールを無視

## 設定（環境変数）

`.env` ファイルで設定。Pydantic Settings で読み込み。全項目は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) の「設定」セクションを参照。

**注意**: `AGENT_COMMAND` と `TRUSTED_PATHS` は JSON 配列形式で指定（例: `["path1", "path2"]`）。

## 参照リンク

- [Agent Client Protocol](https://agentclientprotocol.com/)
- [ACP Python SDK](https://github.com/agentclientprotocol/python-sdk)
- [ACP Python SDK Quick Start](https://agentclientprotocol.github.io/python-sdk/quickstart/)
- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [discord.py GitHub](https://github.com/Rapptz/discord.py)
