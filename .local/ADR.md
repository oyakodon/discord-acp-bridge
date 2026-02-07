# Architecture Decision Record: discord-acp-bridge

## ADR-001: 開発言語とフレームワークの選定

**Status:** Accepted
**Date:** 2026-02-03

---

## Context

Discord Gateway Botとして常駐し、Agent Client Protocol (ACP) を通じてAIエージェントと対話するアプリケーションを構築する。

技術選定にあたり、以下の制約と要件がある：

- ACP公式SDKが提供されている言語から選択
- Discord Botライブラリが成熟している必要がある
- 開発者はTypeScriptとPythonの両方に習熟

---

## Considered Options

### Option 1: TypeScript + discord.js

| 項目 | 詳細 |
|------|------|
| **ACP SDK** | `@zed-industries/agent-client-protocol` |
| **Discord** | discord.js v14.x (安定) / v15.x (プレリリース) |
| **Runtime** | Node.js 24.x LTS |

**Pros:**
- discord.jsは最も利用者が多く、ドキュメント・コミュニティが充実
- ACP自体がTypeScriptで開発されており、型定義が最も正確
- Node.jsのイベント駆動モデルがDiscord Gatewayと相性が良い
- npmエコシステムが豊富

**Cons:**
- discord.js v15への移行が将来必要になる可能性
- Node.jsのメモリ消費がPythonより大きい傾向
- コールバック地獄を避けるための設計が必要

### Option 2: Python + discord.py

| 項目 | 詳細 |
|------|------|
| **ACP SDK** | `agent-client-protocol` (PyPI) |
| **Discord** | discord.py v2.x |
| **Runtime** | Python 3.12+ |

**Pros:**
- discord.pyは成熟しており、async/awaitによる直感的な非同期処理
- ACP Python SDKはPydanticモデルでスキーマ検証が組み込み
- AIエコシステム（LangChain, LlamaIndex等）との連携が容易
- デプロイが比較的シンプル

**Cons:**
- discord.pyのメンテナンス履歴に不安（2021年に一度開発停止、その後復活）
- GIL（Global Interpreter Lock）によるCPUバウンド処理の制限
- 型ヒントは任意であり、ランタイムエラーのリスク

### Option 3: Rust + serenity

| 項目 | 詳細 |
|------|------|
| **ACP SDK** | `agent-client-protocol` (crates.io) |
| **Discord** | serenity / twilight |
| **Runtime** | Native binary |

**Pros:**
- 最高のパフォーマンスとメモリ効率
- 型安全性が高く、コンパイル時にバグを検出
- シングルバイナリでデプロイが容易

**Cons:**
- 開発速度が遅い（学習コスト含む）
- Discord Botエコシステムがnode/pythonほど成熟していない
- MVPには過剰なエンジニアリング

### Option 4: Kotlin + kord

| 項目 | 詳細 |
|------|------|
| **ACP SDK** | `com.agentclientprotocol:acp` |
| **Discord** | Kord / JDA |
| **Runtime** | JVM (GraalVM Native Image可) |

**Pros:**
- JetBrains Koogフレームワークとの連携
- JVM上で安定した動作
- Null安全、コルーチンによる非同期処理

**Cons:**
- JVMの起動時間・メモリオーバーヘッド
- Discord Botとしての利用事例が少ない
- 開発者の習熟度が低い

---

## Evaluation Criteria

| 基準 | 重み | 説明 |
|------|------|------|
| SDK成熟度 | 高 | ACP SDKの安定性・ドキュメント |
| Discordライブラリ成熟度 | 高 | 長期サポート・コミュニティ |
| 開発効率 | 中 | MVP迅速構築のしやすさ |
| 運用性 | 中 | デプロイ・監視のしやすさ |
| 将来性 | 低 | 長期的なエコシステムの方向性 |

### 評価マトリクス

| Option | SDK成熟度 | Discord成熟度 | 開発効率 | 運用性 | 将来性 | 総合 |
|--------|-----------|---------------|----------|--------|--------|------|
| TypeScript | ◎ | ◎ | ○ | ○ | ○ | **A** |
| Python | ○ | ○ | ◎ | ◎ | ○ | **A** |
| Rust | ○ | △ | △ | ◎ | ○ | B |
| Kotlin | △ | △ | ○ | △ | ○ | C |

---

## Decision

**Option 2: Python + discord.py を採用**

### 決定理由

1. **ACP Python SDKの品質**
   - Pydanticによる自動バリデーション
   - 公式Organization配下に移行済みで継続的メンテナンスが期待できる
   - `acp.helpers`がTypeScript/Go SDKと同等のAPIを提供

2. **discord.pyの現状**
   - 2021年の開発停止後、活発にメンテナンス再開
   - v2.xは安定しており、大規模Botでの実績多数
   - asyncioとの統合が自然

3. **開発効率**
   - Pythonの動的型付けによる高速なプロトタイピング
   - 型ヒント + mypyで必要に応じて静的解析も可能
   - AIエコシステムとの将来的な連携を視野に入れられる

4. **運用性**
   - Docker化が容易
   - systemd/supervisorでのプロセス管理がシンプル
   - メモリフットプリントが比較的小さい

### TypeScriptを選ばなかった理由

- discord.js v14→v15の移行が控えており、破壊的変更のリスク
- ACPのリファレンス実装がTypeScriptであるメリットはあるが、Python SDKも十分成熟
- 本プロジェクトはCPU集約的処理が少なく、Node.jsの強みを活かしきれない

### Rust/Kotlinを選ばなかった理由

- MVPフェーズでは開発速度を優先
- Discord Botエコシステムの成熟度がnode/pythonに劣る
- 開発者の習熟度を考慮

---

## ADR-002: ソフトウェアアーキテクチャ

**Status:** Accepted
**Date:** 2026-02-03

---

## Context

Python + discord.py + ACP Python SDKの構成で、保守性・テスタビリティを確保したアーキテクチャを設計する。

---

## Decision

### レイヤードアーキテクチャ（3層）

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

### プロジェクト構成

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
│       │   │   └── agent.py        # /agent start, /agent stop
│       │   └── events/             # Event Handlers
│       │       ├── __init__.py
│       │       └── message.py      # on_message
│       ├── application/
│       │   ├── __init__.py
│       │   ├── session.py          # セッション管理
│       │   ├── project.py          # プロジェクト管理
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

### 依存関係

```toml
[project]
name = "discord-acp-bridge"
requires-python = ">=3.12"

[project.dependencies]
"discord.py" = "^2.4.0"
"agent-client-protocol" = "^0.6.0"
"pydantic" = "^2.0"
"pydantic-settings" = "^2.0"
"python-dotenv" = "^1.0"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "mypy>=1.11",
    "ruff>=0.6",
]
```

### 通信方式

| 方式 | 実装 | 優先度 |
|------|------|--------|
| stdio (JSON-RPC) | `acp.transports.StdioTransport` | MVP |
| WebSocket | `acp.transports.WebSocketTransport` | 将来 |

### Discordインタラクション設計

**Slash Commands:**

| コマンド | 説明 |
|---------|------|
| `/project list` | 利用可能なプロジェクト一覧 |
| `/project switch <name>` | プロジェクト切り替え |
| `/agent start` | エージェントセッション開始 |
| `/agent stop` | エージェントセッション終了 |
| `/agent status` | 現在のセッション状態表示 |

**メッセージ対話:**

- Botへのメンション or スレッド内リプライでエージェントに送信
- 応答はMarkdown整形してDiscordメッセージとして返却
- 長文は分割 or ファイル添付

---

## Consequences

### Positive

- Python + discord.pyの成熟したエコシステムを活用
- Pydanticによる型安全なデータ処理
- AIエコシステムとの将来的な連携が容易
- テストがシンプルに書ける（pytest-asyncio）

### Negative

- discord.pyのメンテナンス継続性リスク（過去の停止歴）
- TypeScript版ACPとの微妙なAPI差異の可能性

### Risks

- ACP仕様の破壊的変更
- discord.pyの将来的なメンテナンス状況

### Mitigations

- ACP Client層を抽象化し、SDK変更の影響を局所化
- discord.pyの代替（Pycord等）への移行パスを意識した設計

---

## References

- [Agent Client Protocol](https://agentclientprotocol.com/)
- [ACP Python SDK](https://github.com/agentclientprotocol/python-sdk)
- [ACP Python SDK Quick Start](https://agentclientprotocol.github.io/python-sdk/quickstart/)
- [discord.py Documentation](https://discordpy.readthedocs.io/)
- [discord.py GitHub](https://github.com/Rapptz/discord.py)
- [Node.js Releases](https://nodejs.org/en/about/previous-releases)
- [TypeScript 5.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-9.html)

---

## ADR-003: プロジェクト切り替え機能の廃止

**Status:** Accepted
**Date:** 2026-02-07

---

## Context

当初の設計では、以下のワークフローを想定していた：

1. `/project list` でプロジェクト一覧を表示
2. `/project switch <id>` でアクティブプロジェクトを設定
3. `/agent start` でセッション開始（アクティブプロジェクトを使用）

この設計には以下の課題があった：

- **ステートフルな設計**: アクティブプロジェクトという状態をApplication層で保持する必要がある
- **UXの複雑さ**: セッション開始までに2つのコマンド実行が必要
- **明示性の欠如**: `/agent start` 実行時にどのプロジェクトが使われるか不明確
- **エラーハンドリング**: アクティブプロジェクト未設定時のエラー処理が必要

---

## Considered Options

### Option 1: 現状維持（/project switch を残す）

**Pros:**
- 頻繁に同じプロジェクトを使う場合、2回目以降は `/agent start` だけで済む
- デフォルトプロジェクトの概念が明確

**Cons:**
- 状態管理の複雑さ
- ユーザーが現在のアクティブプロジェクトを忘れる可能性
- エラーハンドリングの追加が必要

### Option 2: /agent start にproject_idを必須化し、/project switch を廃止

**Pros:**
- ステートレスな設計（アクティブプロジェクトの状態が不要）
- 明示的なプロジェクト指定により、誤操作を防ぐ
- コマンドがシンプルになる（`/project list` → `/projects` に単純化可能）
- コードの複雑性が減少

**Cons:**
- 毎回project_idを指定する必要がある
- 同じプロジェクトで繰り返し作業する場合、若干手間が増える

### Option 3: 両方をサポート（project_idをオプショナルにする）

**Pros:**
- 柔軟性が高い
- 両方のユースケースに対応

**Cons:**
- 最も複雑な実装になる
- 「どちらを使うべきか」の判断が必要になり、認知負荷が増える

---

## Decision

**Option 2: /agent start にproject_idを必須化し、/project switch を廃止**

### 決定理由

1. **ステートレスな設計の優位性**
   - アクティブプロジェクトの状態管理が不要
   - `ProjectService._active_project_id` フィールドと `get_active_project()` / `switch_project()` メソッドを削除できる
   - `Project.is_active` フィールドも不要になる

2. **明示性の向上**
   - `/agent start project_id:123` で、どのプロジェクトでセッションを開始するか一目瞭然
   - アクティブプロジェクトの確認が不要

3. **UXの簡素化**
   - `/projects` → `/agent start project_id:X` の2ステップで完結
   - 従来は3ステップ（list → switch → start）

4. **エラーケースの削減**
   - 「アクティブプロジェクトが未設定」エラーが発生しなくなる
   - プロジェクトが見つからないエラーのみに集約

5. **オートコンプリート機能との相性**
   - `/agent start` の `project_id` 引数にオートコンプリートを実装することで、毎回の入力負荷を軽減できる
   - プロジェクト名で部分一致検索が可能になり、IDを覚える必要がない

### Option 3を選ばなかった理由

- 柔軟性よりもシンプルさを優先
- 実装の複雑さに見合うメリットが少ない
- オートコンプリート機能により、Option 2のデメリット（毎回入力の手間）が解消される

---

## Implementation Changes

### 削除された機能

1. **Slash Commands:**
   - `/project switch` コマンドを削除
   - `/project list` → `/projects` にリネーム（グループ化が不要になったため）

2. **Application Layer (`application/project.py`):**
   - `ProjectService._active_project_id: int | None` フィールドを削除
   - `get_active_project() -> Project | None` メソッドを削除
   - `switch_project(project_id: int) -> Project` メソッドを削除
   - `Project.is_active: bool` フィールドを削除

3. **Tests:**
   - `test_list_projects_with_active()` を削除
   - `test_get_active_project_none()` を削除
   - `test_get_active_project_exists()` を削除
   - `test_get_active_project_invalid_id()` を削除
   - `test_switch_project_success()` を削除
   - `test_switch_project_not_found()` を削除

### 追加された機能

1. **Slash Commands:**
   - `/agent start` に `project_id` 引数を必須化
   - `/agent start` の `project_id` にオートコンプリート機能を実装（予定）

---

## Consequences

### Positive

- コードベースの複雑性が減少（約120行のコード削減）
- 状態管理が不要になり、バグの可能性が減少
- ユーザーが明示的にプロジェクトを指定するため、誤操作が減少
- テストケースが削減され、保守性が向上

### Negative

- 同じプロジェクトで繰り返し作業する場合、毎回project_idを指定する必要がある
  → オートコンプリート機能で緩和

### Risks

- ユーザーがプロジェクトIDを覚える必要がある
  → `/projects` コマンドですぐに確認可能 + オートコンプリート機能で緩和

---

## References

- [Discord.py Autocomplete](https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.app_commands.Command.autocomplete)
