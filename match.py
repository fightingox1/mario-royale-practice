from twisted.internet import reactor
from buffer import Buffer
import os
import json
import random
import jsonschema

class Match(object):
    def __init__(self, server, roomName, private):
        self.server = server

        self.forceLevel = ""
        self.customLevelData = ""
        self.world = "lobby"
        self.roomName = roomName
        self.closed = False
        self.private = private
        self.playing = False
        self.autoStartTimer = None
        self.startingTimer = None
        self.startTimer = int()
        self.votes = int()
        self.winners = int()
        self.lastId = -1
        self.players = list()

        self.goldFlowerTaken = bool()

    def getNextPlayerId(self):
        self.lastId += 1
        return self.lastId

    def addPlayer(self, player):
        self.players.append(player)
        return self.getNextPlayerId()

    def removePlayer(self, player):
        if player not in self.players:
            return
        self.players.remove(player)
        
        if len(self.players) == 0:
            try:
                self.startingTimer.cancel()
            except:
                pass
            try:
                self.autoStartTimer.cancel()
            except:
                pass
            self.server.removeMatch(self)
            return
        
        if not player.dead and not player.win: # Don't kill podium players
            self.broadBin(0x11, Buffer().writeInt16(player.id)) # KILL_PLAYER_OBJECT

        self.broadPlayerList()

        if player.voted:
            self.votes -= 1
        elif self.server.enableVoteStart and not self.playing and self.votes >= len(self.players) * self.server.voteRateToStart:
            self.start()

    def getPlayer(self, pid):
        for player in self.players:
            if player.id == pid:
                return player
        return None
            
    def getWinners(self):
        self.winners += 1
        return self.winners

    def broadJSON(self, j):
        for player in self.players:
            if not player.loaded:
                continue
            player.sendJSON(j)

    def broadBin(self, code, buff, ignore = None):
        buff = buff.toBytes() if isinstance(buff, Buffer) else buff
        for player in self.players:
            if not player.loaded or (ignore is not None and player.id == ignore):
                continue
            player.sendBin(code, buff)

    def broadLoadWorld(self):
        for player in self.players:
            player.loadWorld(self.world, self.customLevelData)

    def broadStartTimer(self, time):
        self.startTimer = time * 30
        for player in self.players:
            if not player.loaded:
                continue
            player.setStartTimer(self.startTimer)
        
        if time > 0:
            reactor.callLater(1, self.broadStartTimer, time - 1)
        else:
            self.closed = True

    def broadPlayerList(self):
        data = self.getPlayersData()
        for player in self.players:
            if not player.loaded:
                continue
            player.sendJSON({"packets": [
                {"players": (data + ([player.getSimpleData()] if player.dead else [])),
                 "type": "g12"}
            ], "type": "s01"})

    def getPlayersData(self):
        playersData = []
        for player in self.players:
            if not player.loaded or player.dead:
                continue
            playersData.append(player.getSimpleData())
        return playersData

    def onPlayerReady(self, player):
        if not self.private and not self.playing: # Ensure that the game starts even with fewer players
            try:
                self.autoStartTimer.cancel()
            except:
                pass
            self.autoStartTimer = reactor.callLater(30, self.start, True)

        if self.world == "lobby" and self.goldFlowerTaken:
            self.broadBin(0x20, Buffer().writeInt16(-1).writeInt8(0).writeInt8(0).writeInt32(458761).writeInt8(0))

        if self.world == "lobby" or not player.lobbier or self.closed:
            for p in self.players:
                if not p.loaded or p == player:
                    continue
                player.sendBin(0x10, p.serializePlayerObject())
            if self.startTimer != 0 or self.closed:
                player.setStartTimer(self.startTimer)
        self.broadPlayerList()

        if not self.playing:
            if self.startingTimer is None and len(self.players) >= self.server.playerCap:
                self.startingTimer = reactor.callLater(3, self.start, True)
            # This is needed because if the votes where sufficient to start but there wasn't sufficient players,
            # when someone enters the game, it can make it possible to start the game.
            elif self.server.enableVoteStart and self.votes >= len(self.players) * self.server.voteRateToStart:
                self.startingTimer = reactor.callLater(3, self.start, True)

    def voteStart(self):
        self.votes += 1
        if self.server.enableVoteStart and not self.playing and self.votes >= len(self.players) * self.server.voteRateToStart:
            self.start()

    def start(self, forced = False):
        if self.playing or (not forced and len(self.players) < (1 if self.private else self.server.playerMin)): # We need at-least 10 players to start
            return
        self.playing = True
        
        try:
            self.startingTimer.cancel()
        except:
            pass
        
        try:
            self.autoStartTimer.cancel()
        except:
            pass
        
        self.world = self.forceLevel if self.forceLevel != "" else random.choice(self.server.worlds)
        self.broadLoadWorld()

        reactor.callLater(1, self.broadStartTimer, self.server.startTimer)

    def validateCustomLevel(self, level):
        lk = json.loads(level)
        jsonschema.validate(instance=lk, schema=levelJsonSchema)

    def selectLevel(self, level):
        if not self.private:
            return
        if level == "" or level in self.server.worlds:
            self.forceLevel = level
            self.broadLevelSelect()

    def broadLevelSelect(self):
        for player in self.players:
            player.sendJSON({"type":"gsl", "name":self.forceLevel, "status":"update", "message":""})

    def selectCustomLevel(self, level):
        if not self.private:
            return
        self.validateCustomLevel(level)
        self.forceLevel = "custom"
        self.customLevelData = level
        self.broadLevelSelect()
