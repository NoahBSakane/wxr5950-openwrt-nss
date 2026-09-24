# WXR-5950AX12 OpenWrt NSS ビルド

Buffalo WXR-5950AX12 専用のファームウェアを、[qosmio/openwrt-ipq の 24.10-nss](https://github.com/qosmio/openwrt-ipq/tree/24.10-nss) を基に GitHub Actions（Ubuntu 24.04）でビルドします。NSS seed 設定を使い、ほかの機種を無効化し、指定パッケージが `make defconfig` 後もすべて組み込まれていることを検証します。依存パッケージは [OpenWrt公式のビルド環境設定](https://openwrt.org/docs/guide-developer/toolchain/install-buildsystem) を参照しています。

## ビルド方法

この一式をGitHubリポジトリのデフォルトブランチへ配置し、Actionsを有効にした状態で実行します。ローカルのみの状態では実行できません。ワークフロー用の秘密情報の登録は不要です。GitHub CLIは対象リポジトリで認証済みの状態を前提とします。

```sh
gh workflow run build.yml -f ref=24.10-nss
gh run list --workflow build.yml
gh run watch <RUN_ID>
gh run download <RUN_ID> --dir artifacts
```

Actions画面の「Run workflow」からも実行できます。`ref` にはフォークのブランチ名、タグ名、完全なコミットSHA（40桁）を指定できます。指定した版にNSS seedと対象機種が必要です。実際のコミットSHAは実行サマリと成果物に記録されます。feedsは実行時に更新されるため、フォークのSHA指定だけでは完全な再現性は保証されません。

## 成果物

`wxr-5950ax12-nss-<SHA先頭12桁>` として30日間保存します。`bin/targets/qualcommax/ipq807x/` 内の次のファイルと、`fork-commit.txt`（フォークの完全なSHA）を含みます。

- `*buffalo_wxr-5950ax12*`：対象機種のファームウェアなど
- `sha256sums`：上流ビルドが生成したチェックサム一覧（未収集ファイルの項目を含む場合があります）
- `*.manifest`：組み込みパッケージ一覧
- `config.buildinfo`、`feeds.buildinfo`、`version.buildinfo`：設定・feeds・バージョン情報

ソースのダウンロードはキャッシュします。並列ダウンロード・ビルドが失敗した場合は、それぞれ単一ジョブの `V=s` で再実行し、Actionsログに詳細を出力します。

## パッケージ追加

`config/packages.txt` にOpenWrtのパッケージ名を1行ずつ追加します。空行と `#` 以降のコメントは無視します。指定は `CONFIG_PACKAGE_<name>=y` として反映され、存在しないパッケージや依存条件を満たせないものは設定検証で名前を表示して失敗します。

`tcpdump-mini` を指定した場合、同じ実行ファイルを提供するseed内の `tcpdump` は無効化します。両方の同時指定はエラーになります。

## NSS利用時の注意

[フォークの注意事項](https://github.com/qosmio/openwrt-ipq/tree/24.10-nss#important-note) に従い、標準のsoftware/hardware flow offloadingとpacket steeringを無効にしてください。既存設定を引き継ぐ場合も確認が必要です。ブリッジVLANフィルタリング（DSA形式の `config bridge-vlan`）はNSS Wi-Fiオフロード非対応です。このワークフローは実機の設定変更やファームウェア書き込みを行いません。
