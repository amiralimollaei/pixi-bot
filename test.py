from pixi.caching import AudioCache


cache = AudioCache(open("/home/amirali/Desktop/music/Toxic - BoyWithUke.mp3", "rb").read())
cache.to_data_url()