from pypresence import Presence
import time

def DiscordRpcThread(Options):
	while True:
		try:
			presence = Presence(1277586728517107744)
			presence.connect()
			a = False
			while True:
				if Options["EnableDiscordRPC"]:
					if not a:
						try:
							presence.update(
								state="github.com/sukkaphat1/CS2pySukk",
								details="FREE CS2 CHEAT",
								start=int(time.time()),
								large_image="cs2py",
								large_text="cs2py",
								small_image="github",
								small_text="Sukkaphat1 on GitHub",
								buttons=[{'label': 'GitHub', 'url': 'https://github.com/sukkaphat1/CS2pySukk'}]
							)
						except Exception as e:
							pass
					a = True
					time.sleep(1)
				else:
					time.sleep(1)
		except:
			time.sleep(30)