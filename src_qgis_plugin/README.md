# 事前準備&tips

## プラグイン実行に必要なライブラリをQGIS環境にインストールする方法

- OSgeo4W shellを管理者権限で開き、以下のコマンドを実行
```
pip install -r 'path/to/requirements.txt'
```
※'path/to/requirements.txt'：ローカルのazayaka\requirements.txtへの絶対パス

## プラグインのアイコン画像変更方法

### OSgeo4W shellを開き、アイコン画像を配置したローカルのdirまで移動
```
cd 'path/to/azayaka_plugin'
```

※windowsではicon.pngは C:\Users\hogehoge\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\azayaka_plugin 配下に存在

### その後以下のコマンドを実行（コンパイル）し、リロード（リロードは後述）
```
pyrcc5 -o resources.py resources.qrc
```

## 開発側でのQGISの動作確認

開発中に毎回pip installするのが手間な場合、ファイルを手動で配置する事も可能

- 1. azayakaのsrcファイル(pip installの対象ファイル群)を以下に配置
    - C:\Users\hogehoge\AppData\Roaming\Python\Python312\site-packages\azayaka

- 2. azayaka\src_qgis_plugin配下のファイルを以下に配置
    - C:\Users\hogehoge\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\azayaka_plugin

- 3. プラグインのリロード
    QGISのプラグイン'Plugin Reloader'を使用するとQGISを再起動しなくて良いため、効率的