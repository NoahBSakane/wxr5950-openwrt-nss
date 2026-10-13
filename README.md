# WXR-5950AX12 OpenWrt NSS EDMA ビルド

Buffalo WXR-5950AX12 専用のファームウェアを、[JuliusBairaktaris/openwrt-ppe-nss](https://github.com/JuliusBairaktaris/openwrt-ppe-nss)（旧 `openwrt-nss-edma`）を基に GitHub Actions（Ubuntu 24.04）でビルドします。OpenWrt main 系の `qca_edma`・`qca_ppe`（DSA）に NSS を組み合わせた構成です。旧 `nss-edma-rework` ブランチは保管終了済みで、既定入力にはその最終タグを使います。[Qualcommax_NSS_Builder](https://github.com/JuliusBairaktaris/Qualcommax_NSS_Builder) の共通設定と1GB機用設定を使い、WXR-5950AX12 だけを有効にします。`make defconfig` 後に機種・メモリプロファイル・パッケージ指定を検証し、指定が落ちた場合は名前を表示して失敗します。

## ビルド方法

この一式をGitHubリポジトリのデフォルトブランチへ配置し、Actionsを有効にした状態で実行します。Actions画面の「Run workflow」で次の入力を指定します。ワークフロー用の秘密情報の登録は不要です。実行にはソース・feeds・依存パッケージを取得できるネットワークが必要です。

| 入力 | 対象 | 既定値 |
| --- | --- | --- |
| `ref` | `JuliusBairaktaris/openwrt-ppe-nss` のブランチ・タグ・完全な40桁コミットSHA | 空欄なら `config/pins.json` の `candidate.ref` |
| `builder_ref` | `JuliusBairaktaris/Qualcommax_NSS_Builder` のブランチ・タグ・完全な40桁コミットSHA | 空欄なら `config/pins.json` の `candidate.builder_ref` |

既定の `candidate` はフォーク `archive/nss-edma-rework-final`、builder `archive/edma-nss-final`、NSS feed `archive/edma-nss-final` のコミットと、記録時点の他の feed 先端です。フォーク・builder のタグ解決結果が記録した SHA と異なるとビルドを停止します。明示した `ref` / `builder_ref` はそれぞれ優先し、feed pins は候補のままです。両者の互換性は実ビルドで確認してください。

指定したフォークには `qualcommax/ipq807x`、WXR-5950AX12、NSS対応が、指定したビルダーには `devices/common/config` と `devices/ipq807x-1g/config` が必要です。実際に取得した両方のSHAは実行サマリと成果物に記録されます。

## ビルド設定

`scripts/prepare-build.sh` はビルダーの `scripts/prepare-build.sh` の `edma-nss` 手順に合わせ、次の順序で準備します。ビルダーのスクリプトをそのまま実行すると複数機種を一度解決・検証するため、機種の無効化とパッケージの上書きを最初の `make defconfig` より前に行います。

1. `config/pins.json` に記録した６つの feed SHA を `src-git <name> <url>^<sha>` 形式で指定し、feedsを更新・インストールする。固定値が欠ける feed は警告して従来の先端追従に戻る。
2. ビルダーの `patches/feeds/edma-nss/<feed>/*.patch` と `patches/tree/edma-nss/*.patch` に続き、自前の `patches/feeds/<feed>/*.patch` を適用する。既に適用済みなら逆適用のdry-runで確認して省略し、適用不能なら失敗する。広告ブロックのキャッシュ復旧修正は feeds の `adblock-fast.uc` に適用し、修正済みのファイルを ROM に入れる。
3. `devices/common/config` → `devices/ipq807x-1g/config` の順で設定を合成し、後の同名シンボルを優先する。ほかの機種と全機種選択を無効化し、`config/packages.txt` と `config/extra-config.txt` を defconfig 前に反映する。後者は BusyBox のカスタム設定と `diff` を有効にし、機種・initramfs・全機種選択・qca-mcs を再有効化する指定は拒否する。
4. `make defconfig` を実行し、ビルダーにならってカスタムfeedの配布リポジトリ設定（`CONFIG_FEED_nss`、`CONFIG_FEED_luci_extra`）を除外する。既定feedの置換に当たる場合は `nss` の配布設定を維持する。
5. `common/files` → `common/files.edma-nss` → `ipq807x-1g/files` → `ipq807x-1g/files.edma-nss` の順に、存在するoverlayをコピーする。SSH設定の権限を `0600` にし、最後に `scripts/overlay-files.sh` で自前の `files/` を重ねる。ビルダーの既存の uci-defaults ファイルには触れず、自前の番号は `90-wxr5950-bake` とする。
6. 指定された非 `n` 設定とパッケージの `y` / `m`、WXR-5950AX12 だけの機種選択、initramfs・全機種選択・tcpdumpの排他を検証する。

ビルダーの複数機種選択方式（`CONFIG_TARGET_MULTI_PROFILE`、`CONFIG_TARGET_PER_DEVICE_ROOTFS`、`CONFIG_TARGET_DEVICE_...`）を維持し、機種は1台だけ選びます。メモリ設定は `CONFIG_NSS_MEM_PROFILE_HIGH=y` と `CONFIG_ATH11K_MEM_PROFILE_1G=y` です。APK形式を有効にします。ビルダーの共通設定に合わせてinitramfsを無効にするため、従来のinitramfsイメージは収集対象として残っていても生成されません。標準の成果物は既存OpenWrtから更新するsysupgradeイメージです。

## 自作自動化の同梱と初回起動

原本は別の非公開リポジトリの `router-scripts/` に置き、`config/bake-map.txt` が元ファイル名・イメージ内のパス・モードを指定します。原本を更新したら `scripts/sync-router-files.sh <router-scripts のパス>` で `files/` を再生成します。同期時はメールアドレス、ntfy のトピックらしい URL、秘密鍵ヘッダ、長いトークンらしい文字列を grep で検出し、該当すれば生成を中止します。生成した `files/etc/wxr5950-baked-paths` は同梱した全パスの一覧です。ビルド後は見つかったビルドルート内の各パスを `files/` と SHA-256 で照合し、不一致なら失敗します。ビルドルートが見つからない場合は警告し、成果物の `baked-files.sha256` で同梱元のハッシュを確認できます。

固定した packages feed の `adblock-fast.uc` は SHA-256 `19727b189472f380b9791b1fc37c4acdec60eea06650f7d845fea8fafbd49315` です。旧ルーター側で記録したパッチ前の `8bd39504…4c28` とは一致しません。固定 feed の原文へのパッチ dry-run は成功していますが、ROM に入った修正後の内容と起動時の shadow 解消はビルド成果物で確認します。

初回起動の `/etc/uci-defaults/90-wxr5950-bake` は、ROM に同じパスが存在する場合に限り、同梱パスを隠す overlay 側のファイルを処理します。パッチからパッケージへ入る `/lib/adblock-fast/adblock-fast.uc` も同じ条件で処理します。同一なら overlay 側を削除し、異なるなら `/root/overlay-shadow-backup-<日時>/` に退避してから取り除き、ROM 版を有効にします。その後、S18 の `adblock-cache-preload` を有効にします。件数と対象パスは syslog と、利用できれば faultlog に記録します。`/etc/sysupgrade.conf` から ROM に存在するこれらのパスの行だけを取り除き、他の保持設定は残します。cron に `natpmp-keepalive`（30分ごと）、`adblock-update`（毎日4:10）、`wan-watch`（5分ごと）、`duckdns-update`（30分ごと）、`config-backup-mail`（日曜4:30）の行がなければ追記します。既存行と順序は保持し、起動途中で cron を再起動しません。処理は再実行しても同じファイルを重複追加しません。

通知・DDNS・メール・VPN 等の設定と秘密情報は同梱しません。具体的には `/etc/notify.conf`、`/etc/duckdns.conf`、`/etc/msmtprc`、`/etc/tailscale`、`/etc/shadow`、`/root/.ssh`、`/etc/ssh/ssh_host_*`、`/etc/backup-cert.pem`、`notify.conf.example` を除外します。`sysupgrade -n` による初期化後もスクリプトと cron の既定は ROM から復元されますが、秘密・個別設定・バックアップ済み状態は別途、安全に復元する必要があります。退避された旧 overlay ファイルは自動的に戻しません。

既定のビルダー設定にはNSSドライバー・ECM・Wi-Fi offload・SQM・NSS管理ツール、NSS firmware 12.5、OpenSSH、OpenSSL、GCC 15、binutils 2.46、LTO・moldなども含まれます。PPEだけを使う別ワークフローの `common-ppe` / `ppe-ipq807x` 設定やパッチ、mesh用の `config.mesh` は使いません。

## 成果物

`wxr-5950ax12-nss-edma-<fork SHA先頭12桁>-<builder SHA先頭12桁>` として30日間保存します。

- `*buffalo_wxr-5950ax12*`：対象機種のファームウェアなど
- `sha256sums`：上流ビルドが生成したチェックサム一覧に `pins-used.json` の SHA-256 を追記したもの（未収集ファイルの項目を含む場合があります）
- `*.manifest`：イメージの組み込みパッケージ一覧
- `config.buildinfo`、`feeds.buildinfo`、`version.buildinfo`：設定・feeds・バージョン情報
- `fork-commit.txt`、`builder-commit.txt`：実際に取得した両リポジトリの完全なSHA
- `pins-used.json`：指定した ref、feed pins、取得した両リポジトリの SHA
- `packages.txt`：今回のパッケージ指定
- `baked-files.sha256`：同梱した31パスの SHA-256 一覧。ビルドルートが見つからない場合も出力します。
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

組み込み指定には `usbutils`（`lsusb`）、`blkid`、`coreutils-stat`（`stat`）も含めます。BusyBox `diff` は `config/extra-config.txt` で有効にします。NSS seedは使用しません。

## NSS利用時の注意

参照フォークはホストのデータパスで起動し、`nss-tools` の `nss` サービスがNSSを有効にする構成です。`nss-status` またはLuCIの「NSS Offload」で状態を確認します。NSSを無効にする設定は `uci set nss.general.enabled='0'; uci commit nss` と再起動です。フォークの `nss-tools` には標準のsoftware/hardware flow offloadingとpacket steeringを無効化する起動時設定が含まれます。設定を引き継ぐ場合も実際の状態を確認してください。

取り込む共通overlayには、WANゾーンの入力を `DROP` にする設定、WAN向けBCP38、NTPサーバーとDHCP option 42、HTTPSリダイレクト、OpenSSHの暗号設定、弱いDH群の除去が含まれます。これらはビルダーの動作を引き継ぐ変更で、SSH接続や起動後の設定に影響します。初期設定には適用済みのUCIマーカーも使われます。このワークフロー自体は実機の設定変更やファームウェア書き込みを行いません。VLAN・ブリッジ・Wi-Fi・VPN・広告ブロック・追加APKの動作はWXR-5950AX12で未検証です。

## 再現性・未検証事項

フォーク・builder・６つのfeedは `config/pins.json` で SHA を記録し、既定ビルドで固定します。実機稼働版の値は `deployed`、次の候補は `candidate` です。候補 feed の先端は 2026-10-12T03:35:49Z に GitHub API で確認しました。固定されない Ubuntu の apt パッケージ、Actions のタグ、ランナーイメージなどがあるため、ビット単位の再現性は保証しません。ビルダーにならって `SOURCE_DATE_EPOCH`・タイムゾーン・ロケール・ビルドユーザー/ホストを固定しても、この制限は残ります。ビルダーへのローカル適応は、このリポジトリのワークフロー・スクリプトの版にも依存します。

参照クローンにはfeedsの取得結果がないため、feed由来の `luci`、`wireguard-tools`、`luci-proto-wireguard`、`natpmpc`、`tailscale`、`iperf3`、`htop`、`adblock-fast`、`luci-app-adblock-fast`、`miniupnpd-nftables`、`mdns-repeater` の名前と依存条件を完全には確認できていません。不存在・依存不能が確定した指定はありません。実行時の `make defconfig` 後の検証で判断します。参照フォークのツリー内では `kmod-wireguard`、`kmod-tun`、`tcpdump-mini`、`ethtool` の定義を確認しています。

この変更では読み取り専用の GitHub API で pins を確認しました。実際のfeeds取得・パッチ適用・`make defconfig`・実ビルド・実機動作は未検証です。参照ビルダーはUbuntu 26.04のランナーを使いますが、このワークフローは従来のUbuntu 24.04と依存パッケージ導入を維持しています。ツールチェーン・ホスト依存・ディスク容量・6時間の制限内での完了は実ビルドで確認が必要です。

## 上流の監視と通知

`.github/workflows/watch-upstream.yml` は月曜 00:00 UTC（日本時間 09:00）と手動で `scripts/watch/check_upstream.py` を起動します。各リポジトリの正式名・アーカイブ状態・既定ブランチ・`archive/*` タグのオブジェクトとコミット・候補 SHA と先端の compare status を読み取ります。フォークの `diverged` は既知のリベースとして説明し、他の分岐は履歴確認の対象とします。feed の変更ファイルは `config/packages.txt` と `config/installed-watch.txt` の名前を使って、対応するパッケージディレクトリを抽出します。後者は実機の `apk list -I` による名前一覧を反映するための雛形で、現状は完全な実機一覧ではありません。

OpenWrt の GHSA は ID で重複排除し、実機ビルド時刻 `config/pins.json` の `deployed.built_at` 以降に公開・更新されたものだけを新規として表示します。それ以前のものは件数のみ示します。対象パッケージが明示されていればその名前を優先し、なければ要約中の完全な単語でインストール済み名と照合します。`sed`・`curl`・`luci` など一般語になり得る名前は、対象パッケージが不明な場合、要約の先頭語だけで照合します。Issue 本文は分類別件数、勧告の一覧、分類別パス件数と代表３件までを表示します。`patched_versions` が空でも修正済みとは判断しません。カーネル 6.18.y、OpenSSL、dnsmasq、hostapd、tailscale、curl は OpenWrt main と packages feed の Makefile から版を読み、候補 pins の版と比べます。比較先がフォークの実際のビルド版とは限らないため、版差は判断材料です。

`scripts/watch/rules.json` のパス規則で S（セキュリティ）、B（インストール済みに効く修正）、R（挙動変更の確認）、N（他機種だけ）に分類します。規則にないパスは「要オーナー確認」とし、取りこぼしが疑われる場合も表示します。状態は孤立した `state` ブランチの `state.json` に pins・観測結果・通知済みダイジェスト・Issue 番号として保存します。ダイジェストが前回通知と異なるときだけ、公開リポジトリの同じ Issue を作成または更新します。ntfy や独自の秘密は使いません。API 取得に失敗した場合は通知済み状態を更新しません。

ビルドには約２時間23分かかります。この仕組みは調査・通知と候補ビルドの入力固定までを対象とし、実機への書き込みは現地のみで行います。
