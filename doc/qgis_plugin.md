## プラグインの概要

- **InSAR処理**: 干渉SAR処理
- **ジオコーディング処理**: SARデータを地理座標系に投影

## プラグイン実行に必要なライブラリをQGIS環境にインストールする方法

- OSgeo4W shellを管理者権限で開き、以下のコマンドを実行
```
pip install -r 'path/to/requirements.txt'
```
※'path/to/requirements.txt'：ローカルのazayaka\requirements.txtへの絶対パス

## 開発側でのQGISの動作確認

開発中に毎回pip installするのが手間な場合、ファイルを手動で配置する事も可能

- 1. azayakaのsrcファイル(pip installの対象ファイル群)を以下に配置
    - C:\Users\hogehoge\AppData\Roaming\Python\Python312\site-packages\azayaka

- 2. azayaka\src_qgis_plugin配下のファイルを以下に配置
    - C:\Users\hogehoge\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\azayaka_plugin
    - ※またはQGISプラグイン管理からzipでinstallも可能（\azayaka\src_azayaka_pluginを事前にzip化しておくこと）

- 3. プラグインのリロード
    QGISのプラグイン'Plugin Reloader'を使用するとQGISを再起動しなくて良いため、効率的

## 参考資料

- [QGIS公式ドキュメント - Pythonプラグインを構成する](https://docs.qgis.org/3.28/ja/docs/pyqgis_developer_cookbook/plugins/plugins.html)
- [QGISのプラグインの実装例 - nujust's blog](https://nujust.hatenablog.com/entry/2023/06/10/101433)
- [QGISプラグインをつくってみよう - エアロトヨタ](https://www.aerotoyota.co.jp/fun/column/52/)
- [PyQtで重い処理をする時に使うべきマルチスレッドとプログレスバーの実装](https://qiita.com/phyblas/items/37ef1b77decbc48c5fa5#%E3%83%97%E3%83%AD%E3%82%B0%E3%83%AC%E3%82%B9%E3%83%90%E3%83%BC)
- [PySide超入門【第23回】QThreadで学ぶマルチスレッド処理と非同期プログラミング入門](https://www.useful-python.com/pyside23-qthread/)
- [PySide超入門【第15回】通知とメッセージ表示！QStatusBarとQMessageBoxの徹底解説](https://www.useful-python.com/pyside15-qstatusbar-qmessagebox/)