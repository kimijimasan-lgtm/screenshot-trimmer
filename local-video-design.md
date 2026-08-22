# ローカル動画モード 設計書

> 作成: 2026-08-03 | Opus 4.6 設計検討

---

## 1. 設計の核心: キャプチャ方式の違い

ローカル動画モード最大のメリットは **getDisplayMedia（画面共有）が不要** になること。

| | YouTube モード | ローカル動画モード |
|---|---|---|
| 映像ソース | YouTube IFrame API（iframe内） | ネイティブ `<video>` 要素 |
| キャプチャ方法 | getDisplayMedia → 画面共有で間接的に取得 | `canvas.drawImage(video)` で直接フレーム取得 |
| 初回の手間 | 「このタブを共有」ダイアログが必要 | **なし（即座にキャプチャ可能）** |
| 画質 | 画面解像度依存（共有ストリームの解像度） | **元動画の解像度そのまま** |

これは単なるモード追加ではなく、ユーザー体験が根本的に良くなるケース。

---

## 2. タブ切り替えUI

### 配置: ヘッダー内、ブランド名の右隣

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 📷 スクショトリマー v0.2  [YouTube][ローカル]  [URL入力...]  [ch] [ch] ⚙│
└─────────────────────────────────────────────────────────────────────────┘
```

- `[YouTube]` `[ローカル]` はピル型トグル（2択スイッチ）
- アクティブ側にアクセントカラー背景
- 小さめのサイズ（ヘッダーの高さに収まる程度）

### タブ切り替え時の挙動

| 要素 | YouTube時 | ローカル時 |
|---|---|---|
| URL入力欄 + 読み込むボタン | 表示 | **非表示** |
| チャンネルアイコン一覧 | 表示 | **非表示** |
| ファイル選択ボタン | 非表示 | **表示** |
| NotebookLMボタン | 表示 | **非表示** |
| 文字起こしボタン | 表示 | **非表示** |
| ジャンプバー（5枠BM） | 表示 | 表示 |
| 再生コントロール | 表示 | 表示 |
| 10秒戻るボタン | 表示 | 表示 |
| 📷シャッターボタン | 表示 | 表示 |
| 画面共有ステータス | 表示 | **非表示** |
| サイドパネル（サムネイル一覧） | 表示 | 表示 |
| 整理画面・レビュー画面 | 表示 | 表示（共通利用） |

### 切り替え時のデータ

- **キャプチャ済み画像（shots配列）はモード切替でクリアしない**。両モードで撮った画像を混在させても整理画面は問題なく動く（単なる画像データの配列なので）
- ブックマーク（bmTimes）は動画単位なのでリセットする

---

## 3. ローカル動画の読み込みUI

### ファイル選択方法（2つ併用）

#### A. ボタンクリック
ヘッダー内に「ファイルを選択」ボタンを配置（既存の「読み込む」ボタンと同じ位置・スタイル）。

```html
<input type="file" accept="video/*" id="localFileInput" hidden>
<button id="localFileBtn" class="load-btn">ファイルを選択</button>
```

#### B. ドラッグ&ドロップ
動画ペイン全体（.video-pane）をドロップゾーンにする。動画未読み込み時のプレースホルダーにD&Dの案内を表示。

```
┌─────────────────────────────────────┐
│                                     │
│    動画ファイルをここにドロップ      │
│    または上のボタンから選択          │
│                                     │
│    対応形式: MP4, WebM, MOV         │
└─────────────────────────────────────┘
```

ドラッグオーバー時にボーダーがアクセントカラーに変化（droptest.html と同じフィードバック）。

---

## 4. ビデオプレイヤーの実装

### 既存構造との共存

現在の `.player-frame` 内の構造:
```
.player-frame
  #player (YouTube IFrame)
  #playerPlaceholder
```

ローカルモード用に追加:
```
.player-frame
  #player (YouTube IFrame) ← YouTube時のみ表示
  #localVideo (native <video>) ← ローカル時のみ表示
  #playerPlaceholder ← 共用
```

### `<video>` 要素の設定

```html
<video id="localVideo" playsinline controls
       style="width:100%;height:100%;display:none;">
</video>
```

- `controls` 属性: ブラウザネイティブのコントロールを表示（シークバー、音量など）
- ただし、既存のカスタムシークバー（.seekbar）も流用可能。どちらを使うかは実装時に判断
- `playsinline`: iOSでインライン再生するために必要

### ファイル読み込みの処理フロー

```javascript
localFileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const url = URL.createObjectURL(file);
  localVideo.src = url;
  localVideo.style.display = 'block';
  // プレースホルダー非表示
  // ブックマークリセット
  // ファイル名をステータスラインに表示
});
```

---

## 5. キャプチャ処理（ローカル動画モード）

これが最もシンプルかつ強力な部分。

```javascript
function grabLocalFrame() {
  const video = document.getElementById('localVideo');
  const c = document.createElement('canvas');
  c.width = video.videoWidth;   // 元動画の解像度
  c.height = video.videoHeight;
  c.getContext('2d').drawImage(video, 0, 0);
  return {
    dataUrl: c.toDataURL('image/png'),
    jpeg: c.toDataURL('image/jpeg', 0.85),
    w: c.width,
    h: c.height
  };
}
```

**YouTube モードとの違い:**
- getDisplayMedia / ensureDisplayStream() の呼び出しが不要
- 画面共有ダイアログが出ない
- player-frame の座標計算（isTabShare / getBoundingClientRect）が不要
- fabArea の visibility 隠しが不要（iframe越しの問題がないため）

### 既存の capture() 関数の分岐

```javascript
async function capture() {
  if (currentMode === 'local') {
    // ローカルモード: 直接キャプチャ
    const shot = grabLocalFrame();
    fireFlash();
    shots.push(shot);
    renderThumbs();
  } else {
    // YouTubeモード: 既存のgetDisplayMedia経由
    // (現在のコードそのまま)
  }
}
```

---

## 6. 再生コントロールの統合

### 共通インターフェース

YouTubeモードは `player` (YT.Player) オブジェクト、ローカルモードは `localVideo` (HTMLVideoElement) を使う。API が異なるので、薄いラッパーを設けるか、各コールサイトで分岐する。

| 操作 | YouTube (YT.Player) | ローカル (HTMLVideoElement) |
|---|---|---|
| 再生 | `player.playVideo()` | `video.play()` |
| 一時停止 | `player.pauseVideo()` | `video.pause()` |
| 現在時刻取得 | `player.getCurrentTime()` | `video.currentTime` |
| 総時間取得 | `player.getDuration()` | `video.duration` |
| シーク | `player.seekTo(t, true)` | `video.currentTime = t` |
| 再生状態 | `player.getPlayerState() === 1` | `!video.paused` |

**推奨: 薄いラッパーオブジェクト**

```javascript
function getActivePlayer() {
  if (currentMode === 'local') {
    return {
      play: () => localVideo.play(),
      pause: () => localVideo.pause(),
      currentTime: () => localVideo.currentTime,
      duration: () => localVideo.duration || 0,
      seekTo: (t) => { localVideo.currentTime = t; },
      isPlaying: () => !localVideo.paused,
      ready: () => localVideo.readyState >= 2,
    };
  } else {
    return {
      play: () => player?.playVideo(),
      pause: () => player?.pauseVideo(),
      currentTime: () => player?.getCurrentTime?.() || 0,
      duration: () => player?.getDuration?.() || 0,
      seekTo: (t) => player?.seekTo(t, true),
      isPlaying: () => player?.getPlayerState?.() === 1,
      ready: () => !!(player?.getDuration?.()),
    };
  }
}
```

このラッパーを使えば、再生ボタン・一時停止・10秒戻る・ブックマーク・シークバー等の全コードが `getActivePlayer()` 経由で統一的に動く。

---

## 7. iPhone動画（.mov / HEVC）の互換性

### ブラウザ別対応状況

| ブラウザ | H.264 (.mp4) | HEVC (.mov) | VP9 (.webm) |
|---|---|---|---|
| Chrome (Win) | OK | HEVC拡張が必要(*1) | OK |
| Edge (Win) | OK | HEVC拡張が必要(*1) | OK |
| Firefox (Win) | OK | 非対応 | OK |
| Safari (Mac/iOS) | OK | OK | 限定的 |

*1: Microsoft Store の「HEVC ビデオ拡張機能」（有料 ¥120 or デバイス製造元版は無料）が必要

### 対策

1. **再生エラー時のフォールバック表示**: `video.addEventListener('error', ...)` でユーザーにわかりやすいメッセージを出す
2. **推奨フォーマットの案内**: プレースホルダーに「MP4推奨。MOV(HEVC)はブラウザによっては再生できません」と記載
3. **アプリ側での変換は行わない**: FFmpeg.wasmなどの導入はスコープ外（重すぎる）

```javascript
localVideo.addEventListener('error', () => {
  setStatus('この動画形式は再生できません。MP4(H.264)形式への変換をお試しください。', true);
});
```

---

## 8. 整理完了画面（プレビュー + サムネイルグリッド）の共通利用

**結論: そのまま共通利用できる。変更不要。**

理由:
- 整理画面・レビュー画面は `shots[]` 配列（dataUrl + jpeg + w + h）だけに依存
- ローカル動画からのキャプチャも同じ形式で shots に格納される
- トリミング・一括保存・ドラッグ&ドロップ機能もすべてそのまま動く

---

## 9. 実装の影響範囲

### 追加するもの
- HTML: モード切替タブ（2要素）、ファイル選択ボタン、`<video>` 要素、ローカルモード用プレースホルダー
- CSS: タブのスタイル、ドラッグオーバー時のスタイル（計 ~30行）
- JS: モード管理、ファイル読み込み、grabLocalFrame()、getActivePlayer()ラッパー、D&D処理

### 変更するもの
- `capture()` 関数: モード分岐の追加
- 再生コントロール系: ラッパー経由に変更（play/pause/seek/getCurrentTime 等の呼び出し箇所すべて）
- シークバー: ラッパー経由に変更
- ブックマーク: ラッパー経由に変更
- `showView()`: fabArea の表示制御はそのまま

### 触らないもの
- 整理画面（organize view）: 変更なし
- レビュー画面（review view）: 変更なし
- サイドパネル: 変更なし
- 一括保存: 変更なし
- チャンネル登録ロジック: YouTube モード専用のまま（ローカルモードでは呼ばれない）
- 設定パネル（APIキー）: YouTube モード専用

### 推定コード量
- HTML追加: ~20行
- CSS追加: ~40行
- JS追加: ~80行
- JS変更: ~40行（既存の player 直接参照をラッパー経由に）
- **合計: ~180行の追加・変更**（現在の index.html は約1400行）

---

## 10. 実装順序の提案

1. **モード管理の骨格**: `currentMode` 変数、タブUI、切り替え時の表示/非表示
2. **ローカル動画の読み込み**: `<video>` 要素、ファイル選択、D&D、エラーハンドリング
3. **`getActivePlayer()` ラッパー導入**: 既存の player 参照を全てラッパー経由に置換
4. **ローカルキャプチャの実装**: `grabLocalFrame()` + capture() の分岐
5. **動作確認**: 実際に動画ファイルを読み込んでキャプチャ → 整理 → 保存の一連のフローをテスト

---

## 11. 未解決の設計判断（しろちゃんへの確認事項）

### Q1: ネイティブコントロール vs カスタムシークバー
ローカル動画の `<video>` 要素にブラウザネイティブの `controls` を表示するか、既存のカスタムシークバー（ホバーで表示されるやつ）を流用するか？

- **ネイティブ controls**: 実装が楽。音量調整・全画面・再生速度も使える。ただしデザインがブラウザ依存でダークテーマに合わない可能性あり
- **カスタムシークバー流用**: デザイン統一。ただし音量・速度変更は自前実装が必要

**推奨: まずネイティブ controls で実装し、見た目が気になったら後でカスタムに切り替え**

### Q2: ローカル動画のファイル名表示
読み込んだ動画のファイル名をどこに表示するか？

- A案: ステータスライン（現在の位置）
- B案: ヘッダー内のファイル選択ボタンの横

**推奨: A案（ステータスライン）**。既にステータス表示の仕組みがあるので追加コスト0。

### Q3: ローカルモードでも「画面共有中」を使う場面はあるか？
→ ない。ローカルモードでは getDisplayMedia を一切呼ばない設計。

---

## まとめ

- **最大のメリット**: 画面共有なしで直接キャプチャ → UXが大幅に良い
- **実装コスト**: 約180行の追加・変更（既存コード比 13%程度）
- **リスク**: HEVC互換性のみ（エラー表示で対応）
- **整理画面・レビュー画面**: 完全に共通利用可能、変更不要
