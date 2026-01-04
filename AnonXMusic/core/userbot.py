import sys

from unidecode import unidecode

import config

from ..logging import LOGGER

assistants = []
assistantids = []


class Userbot:
    def __init__(self):
        self.one = None
        self.two = None
        self.three = None
        self.four = None
        self.five = None

    def set_clients(self, anony):
        self.one = anony.userbot1 if config.STRING1 else None
        self.two = anony.userbot2 if config.STRING2 else None
        self.three = anony.userbot3 if config.STRING3 else None
        self.four = anony.userbot4 if config.STRING4 else None
        self.five = anony.userbot5 if config.STRING5 else None

    async def start(self):
        LOGGER(__name__).info(f"Initializing Assistants...")
        
        if self.one:
            try:
                await self.one.join_chat("College_wali_masti")
                await self.one.join_chat("Saykkunomusic")
            except:
                pass
            assistants.append(1)
            try:
                await self.one.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 1 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin!"
                )
                exit()
            self.one.id = self.one.me.id
            self.one.name = self.one.me.mention
            if not self.one.me.username:
                LOGGER(__name__).error("Please set username to assistants and restart the bot again")
                sys.exit()
            self.one.username = self.one.me.username
            assistantids.append(self.one.id)
            LOGGER(__name__).info(f"Assistant Started as {unidecode(self.one.name)}")

        if self.two:
            try:
                await self.two.join_chat("College_wali_masti")
                await self.two.join_chat("Saykkunomusic")
            except:
                pass
            assistants.append(2)
            try:
                await self.two.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 2 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin!"
                )
                exit()
            self.two.id = self.two.me.id
            self.two.name = self.two.me.mention
            if not self.two.me.username:
                LOGGER(__name__).error("Please set username to assistants and restart the bot again")
                sys.exit()
            self.two.username = self.two.me.username
            assistantids.append(self.two.id)
            LOGGER(__name__).info(f"Assistant Two Started as {unidecode(self.two.name)}")

        if self.three:
            try:
                await self.three.join_chat("College_wali_masti")
                await self.three.join_chat("Saykkunomusic")
            except:
                pass
            assistants.append(3)
            try:
                await self.three.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 3 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin! "
                )
                exit()
            self.three.id = self.three.me.id
            self.three.name = self.three.me.mention
            if not self.three.me.username:
                LOGGER(__name__).error("Please set username to assistants and restart the bot again")
                sys.exit()
            self.three.username = self.three.me.username
            assistantids.append(self.three.id)
            LOGGER(__name__).info(f"Assistant Three Started as {unidecode(self.three.name)}")

        if self.four:
            try:
                await self.four.join_chat("College_wali_masti")
                await self.four.join_chat("Saykkunomusic")
            except:
                pass
            assistants.append(4)
            try:
                await self.four.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 4 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin! "
                )
                exit()
            self.four.id = self.four.me.id
            self.four.name = self.four.me.mention
            if not self.four.me.username:
                LOGGER(__name__).error("Please set username to assistants and restart the bot again")
                sys.exit()
            self.four.username = self.four.me.username
            assistantids.append(self.four.id)
            LOGGER(__name__).info(f"Assistant Four Started as {unidecode(self.four.name)}")

        if self.five:
            try:
                await self.five.join_chat("College_wali_masti")
                await self.five.join_chat("Saykkunomusic")
            except:
                pass
            assistants.append(5)
            try:
                await self.five.send_message(config.LOGGER_ID, "Assistant Started")
            except:
                LOGGER(__name__).error(
                    "Assistant Account 5 has failed to access the log Group. Make sure that you have added your assistant to your log group and promoted as admin! "
                )
                exit()
            self.five.id = self.five.me.id
            self.five.name = self.five.me.mention
            if not self.five.me.username:
                LOGGER(__name__).error("Please set username to assistants and restart the bot again")
                sys.exit()
            self.five.username = self.five.me.username
            assistantids.append(self.five.id)
            LOGGER(__name__).info(f"Assistant Five Started as {unidecode(self.five.name)}")

    async def stop(self):
        LOGGER(__name__).info(f"Stopping Assistants...")
