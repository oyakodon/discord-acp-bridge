---
name: implement
description: "このプロジェクトの標準開発フロー（featureブランチ作成 → 実装 → コードレビュー → 修正 → 品質チェック → コミット → squash merge）を一気通貫で実行する。新機能の実装、バグ修正、リファクタリングなどを依頼されたときに使用する。例: /implement セッション管理のリファクタリング"
---

# 実装フロー

以下のタスクをこのプロジェクトの標準開発フローに従って実装する：

**タスク:** $ARGUMENTS

## Step 1: featureブランチ作成

- 現在のブランチを確認し、mainでなければ確認を取る
- `git checkout -b feature/<feature-name>` でブランチを作成

## Step 2: 実装

- CLAUDE.md のアーキテクチャとコーディング規約に従う
- 3層アーキテクチャ（Presentation / Application / Infrastructure）を意識する

## Step 3: コードレビュー

- `python-code-reviewer` エージェントで必ずレビューを受ける

## Step 4: レビュー指摘の修正

- Critical/High な問題は必ず対応する

## Step 5: 品質チェック

以下をすべて PASS させる（失敗時は修正して再実行）：

```bash
uv run pytest              # テスト実行
uv run mypy src tests      # 型チェック
uv run ruff check .        # リンティング
```

## Step 6: コミット

- `.claude/*` 以外を適切な粒度でコミット

## Step 7: mainへのsquash merge

```bash
git checkout main
git merge --squash feature/<feature-name>
git commit -m "..."
git branch -D feature/<feature-name>
```
