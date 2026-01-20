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

pypiを毎回更新してpip installするのは手間なので手動で以下のように作業すると楽

- qgis_plugin用のソースファイルの配置
    - azayaka\src_qgis_plugin配下のファイルをローカルのazayaka_plugin配下にコピペ
    - ※windowsでのazayaka_pluginの場所
        - C:\Users\hogehoge\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\azayaka_plugin

- プラグインのリロード
    QGISのプラグイン'Plugin Reloader'を使用するとQGISを再起動しなくて良いため、効率的