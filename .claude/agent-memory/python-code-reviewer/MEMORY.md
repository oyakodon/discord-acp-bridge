# Python Code Reviewer Memory

## プロジェクト概要
Discord Gateway Botとして常駐し、Agent Client Protocol (ACP)経由でAIエージェントと対話するアプリケーション。

## アーキテクチャパターン
- **3層アーキテクチャ**: Presentation / Application / Infrastructure
- **Infrastructure層**: ACP Client、Config、Storageを含む
- **ACP通信**: stdio経由のJSON-RPC（MVP段階）

## コード規約
- **Ruff**: 88文字制限、自動修正有効、複数のルールセット適用
- **型ヒント**: 必須（mypy互換性）
- **非同期**: asyncio/await パターン
- **ログ**: logging モジュール使用

## よく見るパターン

### 設定管理（Config）
- **Pydantic Settings**: `BaseSettings` を使用して環境変数と設定ファイルを統一的に管理
- **フィールドバリデーション**: `@field_validator` で柔軟なパース（JSON文字列 → リスト変換など）
- **シングルトンパターン**: `get_config()` でグローバル設定インスタンスを提供（シングルスレッド前提）
- **ファイル操作**: `Path.read_text()` / `Path.write_text()` でUTF-8エンコーディング明示
- **親ディレクトリ作成**: `Path.mkdir(parents=True, exist_ok=True)` で冪等性を確保
- **JSON保存**: `json.dumps(indent=2, ensure_ascii=False)` で可読性の高いフォーマット

### Application層（サービスクラス）
- **依存注入**: コンストラクタで`Config`を受け取る（テスタビリティ向上）
- **Pydantic BaseModel**: ドメインモデルに使用（バリデーション + 型安全性）
- **カスタム例外**: ドメイン固有の例外に属性を持たせる（`project_id`, `session_id`, `current_state`など）
- **冪等性**: 重複操作時に例外を投げず、既存データを返す（ユーザビリティ重視）
- **パス正規化**: `Path.resolve()`で絶対パスに統一（重複チェック精度向上）
- **状態管理**: Enumで状態を定義し、状態遷移をメソッドで制御
- **コールバックベース非同期通知**: ACP Clientからの通知はコールバック関数で受け取る（`on_session_update`, `on_timeout`）
- **マップ管理**: 複数の検索軸がある場合は逆引きマップを用意（user_id→Session, session_id→Session, thread_id→session_id, acp_session_id→session_id）
  - **注意**: 現時点（2026-02-07）の実装ではacp_session_id→session_idマップが未実装（線形探索している）

### Presentation層（Discord Bot）
- **Cog分割**: Commands（Slash Commands）とEvents（イベントハンドラー）で分離
- **認証デコレーター**: `is_allowed_user()`でSlash Commandsに認証チェックを統一的に適用
- **ephemeral応答**: `ephemeral=True`でコマンド応答をプライベートに
- **defer()パターン**: 3秒以上かかる処理は`interaction.response.defer()`で応答時間を確保
- **タイピングインジケーター**: `async with channel.typing():`で処理中を表示
- **setup_hook()**: Cogのロードとコマンドツリーの同期を実施
- **Slash Commandsのグループ化**: `app_commands.Group`で関連コマンドをグループ化（`/project`, `/agent`）
- **コールバック統合**: SessionServiceにDiscord通知用コールバックを渡し、Application層からPresentation層へ通知
- **スレッドアーカイブ**: セッション終了時に`thread.edit(archived=True)`でスレッドを閉じる
- **スレッド名の制限**: Discord APIの100文字制限に注意（長いパスは切り詰める）

### ACP Client実装
- `acp.spawn_agent_process()` でプロセス起動
- `ClientSideConnection` で通信管理
- `Client` プロトコルの実装が必要（未実装メソッドは警告ログ）
- Watchdog Timerによる30分タイムアウト管理

### エラーハンドリング
- RuntimeError: 初期化チェック（connection is None）
- asyncio.CancelledError: タスクキャンセル時は再raise
- 例外ログ: logger.exception() でスタックトレース記録
- ファイル不存在: 空リストを返す（例外を投げない）→ docstringとの整合性に注意
- JSON パースエラー: 再raiseして呼び出し側に委譲

### リソース管理
- プロセス終了: terminate → wait → kill（タイムアウト時）
- 非同期タスク: cancel() で停止、done() でチェック

### 非同期コールバックパターン
- **同期コールバック内での非同期実行**: `asyncio.create_task()`でタスク化
- **例外の握りつぶしリスク**: `create_task()`で作成したタスクの例外は明示的にハンドルしないと見逃される
- **型アノテーション**: `Callable[..., Awaitable[None]]`とコルーチンの型不一致に注意（mypy警告が出る場合がある）

## レビュー観点
1. 型ヒントの完全性（mypy互換）
2. async/awaitの正しい使用
3. リソースクリーンアップの確実性
4. Watchdog Timerのリセットタイミング
5. ACP Clientプロトコルの実装漏れ
6. **docstringと実装の整合性**（特にRaises節）
7. **Pydantic validator での型検証の徹底**（リスト要素など）
8. **例外ハンドリングの具体性**（`except Exception` は避ける）
9. **asyncio.create_task()の例外ハンドリング**（タスクの例外が握りつぶされないようにする）
10. **コールバック関数の例外処理**（Application層からPresentation層へのコールバックでエラーが発生しても、ログに記録すべき）

## よくある問題パターン

### High優先度
- **設計仕様との不一致**: 実装が設計ドキュメント（Design.md）と異なる場合（戻り値型、状態遷移など）
- **MVP機能の欠落**: MVP要件であるにも関わらず重要機能が未実装（例: エージェント応答のDiscord表示、タイムアウト通知）
- **層間の依存関係の不適切な設計**: Application層がPresentation層に依存してしまう（コールバックでの回避が必要）
- **finally句での状態復元の不適切性**: 例外発生時も無条件に状態を戻してしまう（意図的な場合はコメントで明示、またはエラー時の処理を分岐）
- **asyncio.create_task()の例外握りつぶし**: タスク作成後に例外が発生しても、呼び出し元で検知できない（`add_done_callback()`や`try-except`で明示的にハンドル）
- **mypy警告の無視（`# type: ignore`）の乱用**: 型エラーの根本原因を解決せずに無視している
- **バッファフラッシュ漏れ**: 終了処理時にバッファ内のデータがフラッシュされずに破棄される（セッション終了、タイムアウト時など）
- **Discord API制約違反**: スレッド名の100文字制限、メッセージの2000文字制限などを超過
- **特定の例外をexcept Exceptionで握りつぶし**: カスタム例外（ValueError, RuntimeErrorなど）を汎用的な`except Exception`で握りつぶしてしまう

### Medium優先度
- docstringと実装の不一致（特に例外の扱い）
- Pydantic validatorでのエラーハンドリング不足（不正な入力の扱い）
- 汎用的すぎる例外ハンドリング（`except Exception`）
- **リスト処理の非効率性**: 重複チェックで2回ループ、またはO(n)でアクセスできるところをリスト全体をループ
- **インスタンス生成の冗長性**: 既存オブジェクトを更新できるのに新規インスタンスを作成
- **マップ構造の不十分性**: 複数のキーで検索する必要があるのに、逆引きマップがない（線形探索が発生）
- **状態チェックの不完全性**: 状態遷移図で許可されていない操作のチェック漏れ
- **Cogロード失敗の握りつぶし**: 重要なCogのロード失敗を握りつぶして続行してしまう
- **シャットダウン処理の不完全性**: リソースのクリーンアップが不完全（セッション、ACP Client、プロセスなど）
- **Discord API制約の未考慮**: スレッド名の長さ制限、メッセージの2000文字制限など
- **プライベート属性への外部代入**: `session_service._on_message_callback = ...` のように、初期化後に外部から代入（設計の一貫性欠如）
- **重複コードの放置**: 同じ処理が複数箇所にコピペされている（共通メソッド化すべき）
- **エラーハンドリングの粒度不足**: 複数の処理を1つのtry-exceptで囲み、どの処理で失敗したか分からない

### Low優先度
- 未使用のテストパラメータ（`tmp_path` など）
- 冗長なバリデーター（Pydanticの自動変換で足りる場合）
- シングルトンのスレッドセーフ性（現状は単一スレッド前提で問題なし）
- **datetime.now()のタイムゾーン未指定**: naive datetimeを使用（将来的にUTC化が必要かも）
- **マジックナンバーのハードコード**: ログ出力の文字数制限など
- **アクティビティ更新の散在**: `last_activity_at`の更新が複数箇所に分散
- **on_ready()の複数回呼び出し**: discord.pyの仕様上、再接続時に複数回呼ばれる可能性（現時点では問題なし）

## コードの良い点（テンプレート）
- Pydantic Settings の適切な活用
- 型ヒントの完全性（mypy互換）
- エラーハンドリングの明確さ
- テストカバレッジの充実（正常系・異常系・エッジケース）
- docstringの品質（引数・戻り値・例外の明記）
- discord.pyのベストプラクティス遵守（Cogs、Slash Commands、setup_hook()など）
- 認証チェックの統一的な実装（デコレーターパターン）
- defer()とephemerの適切な使用（UX向上）
- ログ出力の充実（INFO/WARNING/ERROR/DEBUGの適切な使い分け）
- コールバックパターンによる疎結合（Application層とPresentation層の分離）

## 最近のレビュー

### 2026-02-07 (1) - コールバック機構実装
**レビュー対象**: Presentation層（bot.py, commands/agent.py, events/message.py）、Application層（session.py）のコールバック機構、main.pyのコールバック設定

**修正内容**:
- SessionServiceにDiscord通知コールバック（on_message, on_timeout）を追加
- bot.pyにsend_message_to_threadとsend_timeout_notificationメソッドを追加
- main.pyでSessionServiceにコールバックを設定
- _on_session_updateでAgentMessageChunkをDiscordに転送
- _on_timeoutでタイムアウト通知をDiscordに送信

**発見した問題**:
- **High**: send_promptのfinally句で状態復元が無条件に実行される（L286-289）
- **High**: コールバック実行時の例外ハンドリング不足（asyncio.create_task()の例外握りつぶし）
- **High**: `# type: ignore[arg-type]` の使用（mypy警告の無視）
- **Medium**: ACPセッションIDの線形探索（逆引きマップがない）
- **Medium**: message.pyのTODOコメント削除漏れ
- **Medium**: メッセージ分割ロジックの不完全性（Markdown考慮なし）
- **Medium**: bot.get_channel()の失敗ケース処理（Noneチェック不足）
- **Medium**: コールバックのセッター方式による依存注入（プライベート属性への代入）
- **Medium**: Cogロード失敗の握りつぶし

**新しく追加したパターン**:
- 非同期コールバックパターン（同期コールバック内での`asyncio.create_task()`使用）
- コールバック統合パターン（Application層からPresentation層への通知）

### 2026-02-07 (2) - メッセージバッファリング機能
**レビュー対象**: `session.py` のAgentMessageChunk属性アクセス修正とメッセージバッファリング機能

**修正内容**:
- `update.text` → `update.content.text` に修正（TextContentBlock型チェック追加）
- 時間ベースのバッファリング機能（500ms）を追加
- `_message_buffers`, `_flush_tasks`, `_flush_message_buffer()`, `_schedule_buffer_flush()` を実装

**発見した問題**:
- **High**: セッション終了時のバッファフラッシュ不足（最終メッセージが送信されない可能性）
- **High**: フラッシュタスクの例外ハンドリング不足（`asyncio.create_task()`の例外握りつぶし）
- **High**: `# type: ignore[arg-type]` の使用（L442）
- **Medium**: acp_session_id→session_idマップの欠如（線形探索が継続）
- **Medium**: バッファフラッシュタスクのクリーンアップ不足（セッション終了時にキャンセルされない）
- **Medium**: マジックナンバーのハードコード（0.5秒）
- **Low**: `asyncio` の重複インポート（L590）
- **Low**: バッファ初期化の冗長性（`defaultdict`で簡潔にできる）

**新しく追加したパターン**:
- **時間ベースのバッファリング**: デバウンスパターンでAPIリクエストを集約
- **TextContentBlock型チェック**: `isinstance(update.content, TextContentBlock)` で安全にアクセス

### 2026-02-07 (3) - スレッドアーカイブ機能（Phase 1-2）
**レビュー対象**: `commands/agent.py` のstop/killコマンド、`bot.py` のsend_timeout_notification

**修正内容**:
- stop_sessionコマンド実行後にスレッドをアーカイブ（L190-197）
- kill_sessionコマンド実行後にスレッドをアーカイブ（L255-262）
- タイムアウト通知送信後にスレッドをアーカイブ（L96-97）

**発見した問題**:
- **Medium**: スレッドアーカイブ失敗時の例外処理が不十分（セッション終了は成功しているが、エラーメッセージが曖昧）
- **Medium**: スレッドアーカイブ処理の重複コード（stop/killで同じ処理が3箇所に分散）
- **Low**: スレッド名の長さ制限未考慮（Discord APIの100文字制限）
- **Low**: send_timeout_notificationのエラーハンドリング重複（メッセージ送信とアーカイブが同じexceptブロック）

**ベストプラクティス**:
- **スレッドアーカイブの共通化**: `archive_session_thread(thread_id, message)`メソッドでDRY原則を適用
- **エラーハンドリングの分離**: アーカイブ処理を別のtry-exceptブロックで囲み、セッション終了とアーカイブの失敗を区別
- **絵文字の使い分け**: 終了理由に応じて異なる絵文字を使用（🛑=正常終了, ⚠️=強制終了, ⏱️=タイムアウト）

### 2026-02-07 (4) - メッセージdebounce機能（Phase 2-3）
**レビュー対象**: `presentation/events/message.py`, `tests/presentation/test_message.py`

**修正内容**:
- メッセージイベントハンドラーに1秒のdebounce機能を追加
- `DebounceState`データクラスで状態管理（メッセージバッファ、タスク）
- 連続したメッセージを1つにまとめて送信
- asyncio.create_task()とasyncio.sleep()で実装
- 充実したテストカバレッジ（単一/複数メッセージ、タスクキャンセル、エラーハンドリング）

**発見した問題**:
- **Medium**: debounceタスクの例外握りつぶしリスク（`asyncio.create_task()`の例外処理不足）
- **Low**: マジックナンバーのハードコード（DEBOUNCE_DELAY = 1.0）
- **Low**: debounce状態のクリーンアップ不足（セッション終了後もメモリに残る）

**良い点**:
- debounceパターンの正しい実装（タスクキャンセルによるデバウンス）
- 型安全性の確保（dict[tuple[int, int], DebounceState]）
- 充実したテストカバレッジ（正常系・異常系・エッジケース）
- エラーハンドリングの分離（SessionStateErrorと一般的な例外）

**新しく追加したパターン**:
- **メッセージdebounce**: タスクキャンセルによるデバウンス処理（ユーザー入力の集約）
- **複合キーによる状態管理**: `(user_id, thread_id)`でdebounce状態を管理

### 2026-02-07 (5) - プロジェクトIDオプション引数（Phase 3-3）
**レビュー対象**: `application/project.py`, `presentation/commands/agent.py`, `tests/test_project.py`

**修正内容**:
- `/agent start` コマンドに `project_id` オプション引数を追加
- `get_project_by_id()` メソッドを新規追加（Trusted Path検証付き）
- `switch_project()` を `get_project_by_id()` を使うようリファクタリング
- テストケース追加（正常系・異常系）

**発見した問題**:
- **High**: Discord APIのスレッド名制限（100文字）未考慮
- **High**: ValueError発生時のユーザーへのエラーメッセージ不足（汎用的な`except Exception`で握りつぶされる）
- **Medium**: `get_project_by_id()`のTrusted Path検証の冗長性（理論上は常にTrueだが、防御的プログラミングとして有効）
- **Medium**: プロジェクトIDのログ出力の不一致（指定時とアクティブプロジェクト使用時で差がある）
- **Low**: スレッド作成エラーのハンドリング不足（discord.HTTPExceptionを明示的にキャッチしていない）

**良い点**:
- DRY原則の適用（`get_project_by_id()`でコード共通化）
- 防御的なセキュリティチェック（Trusted Path検証 + ERROR ログ）
- 適切な例外ハンドリング（ProjectNotFoundError）
- ユーザーフレンドリーなエラーメッセージ（次の行動を明示）
- 充実したテストカバレッジ

**新しく追加したパターン**:
- **オプショナル引数によるプロジェクト選択**: アクティブプロジェクトまたは明示的なID指定
- **防御的セキュリティチェック**: 理論上は不要だが、将来の変更に備えたTrusted Path検証

### 2026-02-07 (6) - LLM使用量表示機能（Phase 3-1）
**レビュー対象**: `infrastructure/acp_client.py`, `application/session.py`, `presentation/commands/agent.py`

**修正内容**:
- ACP SDK v0.7.1で未実装の`usage_update`型を独自に定義（`UsageUpdate`, `UsageUpdateCost`）
- `Session`モデルに使用量フィールド追加（`context_used`, `context_size`, `total_cost`, `cost_currency`）
- `_on_session_update()`で`UsageUpdate`を処理してセッションに保存
- `/agent usage`コマンド追加（コンテキスト使用量、使用率、累積コストを表示）
- 辞書型のsession_updateを受け入れ、`usage_update`の場合は動的にパース

**発見した問題**:
- **High**: ゼロ除算のリスク（`context_size=0`の場合にクラッシュする可能性）
- **High**: 辞書型の許容による型安全性の低下（将来的にSDK対応時にクリーンアップ必要）
- **Medium**: 未実装型のパース処理の不十分性（パース失敗時のログが不明瞭、未知の型のログレベルが不適切）
- **Medium**: UsageUpdate処理時の例外ハンドリング不足（現在は問題ないが、型定義変更時のリスクあり）
- **Medium**: `field_meta`フィールドの命名規則（Pydanticの標準と異なるが、ACP RFC準拠のため変更不要）
- **Low**: 使用量未取得時のメッセージ冗長性
- **Low**: session_usageコマンドのdocstring不足（Raises節がない）

**良い点**:
- ACP RFC準拠の型定義（将来のSDK対応に備えた設計）
- 型安全性の確保（コールバック型に`UsageUpdate`を追加）
- ログ出力の充実（DEBUG レベルで使用量更新を記録）
- ユーザーフレンドリーなUI（未取得時のメッセージ、数値フォーマット）
- コマンドの一貫性（他のagentコマンドと同じスタイル）

**新しく追加したパターン**:
- **未実装ACP型の独自定義**: SDK未対応の型をPydantic BaseModelで定義し、将来のSDK対応に備える
- **辞書型の動的パース**: `dict[str, Any]`を受け入れ、実行時に特定の型にパースする（型安全性とのトレードオフ）
- **使用量情報の可視化**: コンテキスト使用率とコストをユーザーに分かりやすく表示

**レビューで推奨した改善**:
- ゼロ除算対策の追加（`context_size > 0`チェック）
- 未知の通知タイプのログレベルを`WARNING`から`DEBUG`に変更（ノイズ削減）
- パース失敗時のログに例外詳細を追加
- TODOコメント追加（SDK対応時のクリーンアップタスク）
