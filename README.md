# WXR-5950AX12 OpenWrt NSS EDMA ビルド

Buffalo WXR-5950AX12 専用のファームウェアを、[JuliusBairaktaris/openwrt-nss-edma](https://github.com/JuliusBairaktaris/openwrt-nss-edma) を基に GitHub Actions（Ubuntu 24.04）でビルドします。OpenWrt main 系の `qca_edma`・`qca_ppe`（DSA）に NSS を組み合わせた `nss-edma-rework` ブランチを使います。[Qualcommax_NSS_Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder) の共通設定と1GB機用設定を使い、WXR-5950AX12 だけを有効にします。`make defconfig` 後に機種・メモリプロファイル・パッケージ指定を検証し、指定が落ちた場合は名前を表示して失敗します。

## ビルド方法

この一式をGitHubリポジトリのデフォルトブランチへ配置し、Actionsを有効にした状態で実行します。Actions画面の「Run workflow」で次の入力を指定します。ワークフロー用の秘密情報の登録は不要です。実行にはソース・feeds・依存パッケージを取得できるネットワークが必要です。

| 入力 | 対象 | 既定値 |
| --- | --- | --- |
| `ref` | `JuliusBairaktaris/openwrt-nss-edma` のブランチ・タグ・完全な40桁コミットSHA | `nss-edma-rework` |
| `builder_ref` | `JuliusBairaktaris/Qualcommax_NSS_Builder` のブランチ・タグ・完全な40桁コミットSHA | `016581e7911a7bf273b4fc072fc5d133d13a5409` |

**`ref` の既定値は `nss-edma-rework` です。** ビルダーのワークフロー(`UPSTREAM_REF`)とフォークのREADMEもこのブランチを指定しています。フォークには `main` ブランチもありますが、NSS対応の有無は未確認のため既定にしていません。固定して試す場合は `ref=c55808ed65f74e8797fe8b1d7b727cc0ba4eb276`(2026-10-08時点の先頭)を指定します。いずれもこの一式での実ビルド成功を確認した版ではありません。

指定したフォークには `qualcommax/ipq807x`、WXR-5950AX12、NSS対応が、指定したビルダーには `devices/common/config` と `devices/ipq807x-1g/config` が必要です。実際に取得した両方のSHAは実行サマリと成果物に記録されます。

## ビルド設定

`scripts/prepare-build.sh` はビルダーの `scripts/prepare-build.sh` の `edma-nss` 手順に合わせ、次の順序で準備します。ビルダーのスクリプトをそのまま実行すると複数機種を一度解決・検証するため、機種の無効化とパッケージの上書きを最初の `make defconfig` より前に行います。

1. `nss-packages` の `edma-nss` ブランチを `nss` feed として追加・置換し、feedsを更新・インストールする。
2. ビルダーの `patches/feeds/edma-nss/<feed>/*.patch` と `patches/tree/edma-nss/*.patch` を適用する。既に適用済みなら逆適用のdry-runで確認して省略し、適用不能なら失敗する。
3. `devices/common/config` → `devices/ipq807x-1g/config` の順で設定を合成し、後の同名シンボルを優先する。ほかの機種と全機種選択を無効化し、`config/packages.txt` を最後に反映する。
4. `make defconfig` を実行し、ビルダーにならってカスタムfeedの配布リポジトリ設定（`CONFIG_FEED_nss`、`CONFIG_FEED_luci_extra`）を除外する。既定feedの置換に当たる場合は `nss` の配布設定を維持する。
5. `common/files` → `common/files.edma-nss` → `ipq807x-1g/files` → `ipq807x-1g/files.edma-nss` の順に、存在するoverlayをコピーする。SSH設定の権限を `0600` にする。
6. 指定された非 `n` 設定とパッケージの `y` / `m`、WXR-5950AX12 だけの機種選択、initramfs・全機種選択・tcpdumpの排他を検証する。

ビルダーの複数機種選択方式（`CONFIG_TARGET_MULTI_PROFILE`、`CONFIG_TARGET_PER_DEVICE_ROOTFS`、`CONFIG_TARGET_DEVICE_...`）を維持し、機種は1台だけ選びます。メモリ設定は `CONFIG_NSS_MEM_PROFILE_HIGH=y` と `CONFIG_ATH11K_MEM_PROFILE_1G=y` です。APK形式を有効にします。ビルダーの共通設定に合わせてinitramfsを無効にするため、従来のinitramfsイメージは収集対象として残っていても生成されません。標準の成果物は既存OpenWrtから更新するsysupgradeイメージです。

既定のビルダー設定にはNSSドライバー・ECM・Wi-Fi offload・SQM・NSS管理ツール、NSS firmware 12.5、OpenSSH、OpenSSL、GCC 15、binutils 2.46、LTO・moldなども含まれます。PPEだけを使う別ワークフローの `common-ppe` / `ppe-ipq807x` 設定やパッチ、mesh用の `config.mesh` は使いません。

## 成果物

`wxr-5950ax12-nss-edma-<fork SHA先頭12桁>-<builder SHA先頭12桁>` として30日間保存します。

- `*buffalo_wxr-5950ax12*`：対象機種のファームウェアなど
- `sha256sums`：上流ビルドが生成したチェックサム一覧（未収集ファイルの項目を含む場合があります）
- `*.manifest`：イメージの組み込みパッケージ一覧
- `config.buildinfo`、`feeds.buildinfo`、`version.buildinfo`：設定・feeds・バージョン情報
- `fork-commit.txt`、`builder-commit.txt`：実際に取得した両リポジトリの完全なSHA
- `packages.txt`：今回のパッケージ指定
- `packages/`：`openwrt/bin/` 以下の全生成APKと、存在する `packages.adb`・`index.json`・`APKINDEX.tar.gz`。元のディレクトリ階層を維持するため、例えば `packages/packages/<architecture>/<feed>/` と `packages/targets/qualcommax/ipq807x/packages/` に入ります。

`=m` のパッケージも `packages/` に入ります。依存パッケージと `=y` のAPKもまとめて収集するため、従来よりアーティファクトが大きくなります。manifestはイメージの内容を表し、`=m` の一覧ではありません。APKが1件もなければ収集を失敗させます。ローカルビルドのAPKとインデックスの署名・インストール可否は実機での確認が必要です。

ソースのダウンロードはキャッシュします。並列ダウンロード・ビルドが失敗した場合は、それぞれ単一ジョブの `V=s` で再実行し、Actionsログに詳細を出力します。権限は `contents: read` に限定し、チェックアウトした認証情報は保持しません。

## パッケージ追加

`config/packages.txt` にOpenWrtのパッケージ名を1行ずつ追加します。空行と `#` 以降のコメントは無視します。

```text
luci                  # CONFIG_PACKAGE_luci=y：イメージに組み込む
miniupnpd-nftables=m   # CONFIG_PACKAGE_miniupnpd-nftables=m：APKだけ作る
mdns-repeater=m
```

`name=y` も受け付けます。同じ名前の同じモードは重複をまとめ、`y` と `m` の競合はエラーにします。ビルダーに同名のパッケージ指定があれば `packages.txt` を優先し、ログに元の値と指定値を表示します。依存関係やビルダーの設定で `m` が `y` に変わった場合は、イメージに入りAPKも作られるので許容し、ログに通知を出します。`y` が `m` や `n` に変わった場合と、`m` が `n` になった場合は失敗させます。存在しない名前や満たせない依存を黙って削除することはありません。

`tcpdump-mini` と `tcpdump` は同じ実行ファイルを提供するため、どちらかを指定すると他方を無効化し、両方の同時指定は `=m` を含めてエラーにします。既定のビルダー共通設定には、どちらも明示指定されていません。

現在の指定は、組み込みが `luci`、`kmod-wireguard`、`wireguard-tools`、`luci-proto-wireguard`、`natpmpc`、`tailscale`、`kmod-tun`、`iperf3`、`htop`、`tcpdump-mini`、`ethtool`、`adblock-fast`、`luci-app-adblock-fast`、APKだけ作るものが `miniupnpd-nftables`、`mdns-repeater` です。`luci`・`iperf3`・`htop`・`kmod-tun` は既定のビルダー共通設定と重複し、`ethtool` はフォークの `nss-tools` の依存にも含まれます。NSS seedは使用しません。

## NSS利用時の注意

参照フォークはホストのデータパスで起動し、`nss-tools` の `nss` サービスがNSSを有効にする構成です。`nss-status` またはLuCIの「NSS Offload」で状態を確認します。NSSを無効にする設定は `uci set nss.general.enabled='0'; uci commit nss` と再起動です。フォークの `nss-tools` には標準のsoftware/hardware flow offloadingとpacket steeringを無効化する起動時設定が含まれます。設定を引き継ぐ場合も実際の状態を確認してください。

取り込む共通overlayには、WANゾーンの入力を `DROP` にする設定、WAN向けBCP38、NTPサーバーとDHCP option 42、HTTPSリダイレクト、OpenSSHの暗号設定、弱いDH群の除去が含まれます。これらはビルダーの動作を引き継ぐ変更で、SSH接続や起動後の設定に影響します。初期設定には適用済みのUCIマーカーも使われます。このワークフロー自体は実機の設定変更やファームウェア書き込みを行いません。VLAN・ブリッジ・Wi-Fi・VPN・広告ブロック・追加APKの動作はWXR-5950AX12で未検証です。

## 再現性・未検証事項

フォークとビルダーを完全なSHAで固定しても、feedsは実行時に更新されます。NSS feedの `edma-nss` ブランチ、ほかのfeeds、Ubuntuのaptパッケージ、Actionsのタグとランナーイメージが変わるため、ビット単位の再現性は保証しません。`feeds.buildinfo` は取得したfeedsの追跡に使えますが、今回のワークフローはそのSHAを指定して再取得する仕組みを持ちません。ビルダーにならって `SOURCE_DATE_EPOCH`・タイムゾーン・ロケール・ビルドユーザー/ホストを固定しても、この制限は残ります。ビルダーへのローカル適応は、このリポジトリのワークフロー・スクリプトの版にも依存します。

参照クローンにはfeedsの取得結果がないため、feed由来の `luci`、`wireguard-tools`、`luci-proto-wireguard`、`natpmpc`、`tailscale`、`iperf3`、`htop`、`adblock-fast`、`luci-app-adblock-fast`、`miniupnpd-nftables`、`mdns-repeater` の名前と依存条件を完全には確認できていません。不存在・依存不能が確定した指定はありません。実行時の `make defconfig` 後の検証で判断します。参照フォークのツリー内では `kmod-wireguard`、`kmod-tun`、`tcpdump-mini`、`ethtool` の定義を確認しています。

この変更はネットワークを使わず参照クローンから調査したもので、実際のfeeds取得・パッチ適用・`make defconfig`・実ビルド・実機動作は未検証です。参照ビルダーはUbuntu 26.04のランナーを使いますが、このワークフローは従来のUbuntu 24.04と依存パッケージ導入を維持しています。ツールチェーン・ホスト依存・ディスク容量・6時間の制限内での完了は実ビルドで確認が必要です。
