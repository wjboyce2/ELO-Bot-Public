import discord
from discord.ext import commands, tasks
import math
import os
import json
from datetime import datetime, timezone, timedelta
import certifi
from discrod.ext import commands
os.environ["SSL_CERT_FILE"] = certifi.where()

BOT_TOKEN = " "                                                #ELO Bot token 
CHANNEL_ID =                                                   #Your discord channel ID
CHAT_ID =                                                      #Specific channel in discord that you want the bot to write to
ADMIN_ID =                                                     #The ID of the admin

#Constants
intents = discord.Intents.default()
intents.message_content = True
K_FACTOR = 100
ranking_diff = False
pause_mode = False
DECAY_FACTOR = 0.98
INACTIVITY_THRESHOLD = timedelta(weeks=2)
DECAY_PERIOD_DAYS = 14
pause_elo_decay = False
utc = timezone.utc
decay_time = datetime.now(utc).replace(hour=3, minute=00, second=0).time() #Decay at 10 PM EST

bot = commands.Bot(command_prefix='$', intents=intents)

#Load player data from JSON file
def load_data():
          if os.path.exists("player_info.json"):
                with open("player_info.json", "r") as f:
                        return json.load(f)
                return{}

#Save player data to JSON file
def save_data():
        with open("player_info.json", "w") as f:
                json.dump(players,f)

#Get ranked players sorted by ELO (highest first)
def get_ranked_players():
        return sorted(players.items(), key=lambda x: x[1]['elo'], reverse=True)

#Get neardby players based on the player's rank
def get_nearby_players(player_rank):
        ranked_players = get_ranked_players()
        lower_bound = max(0,player_rank - 3)
        upper_bound = min(len(ranked_players) - 1, player_rank + 3)
        return ranked_players[lower_bound:upper_bound + 1]

#Calculate the Elo change based on the math results
def calculate_elo_change(team_a_rating, team_b_rating, team_a_won):
        if(team_a_won):
                expected = 1 / (1+math.pow(10, (team_b_rating - team_a_rating) / 400))
                change = K_FACTOR * (1 - expected)

        return int(change)

#Update the player date with the 'last_game' timestamp
def update_activity(player_id):
        players[player_id]['last_game'] = datetime.now().isoformat()
        save_data()

#Initialize player data and active matches
players = load_data()
active_matches = {}

@bot.event
async def on_ready():
        print(f'Logged in as {bot.user}!')
        channel = bot.get_channel(CHANNEL_ID)
        apply_elo_decay.start()
        chat = bot.get_channel(CHAT_ID)
        if chat:
                await chat.send("ELO Bot is Active")

@bot.command()
async def join(ctx):
        #Ask user for their name
        await ctx.send("Please enter your name:")

        #Wait for the user's response
        def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

        try:
        #Wait for the user's message with a timeout of 30 seconds
                msg = await bot.wait_for('message', check=check, timeout = 30)
                name = msg.content

                if str(ctx.author.id) not in players:
                        players[str(ctx.author.id)] = {"name":name, "elo": 1000}
                        save_data()
                        await ctx.send(f"{name}, you have joined the leaderboard with an ELO of 1000!")
                else:
                        await ctx.send(f"{ctx.author.mention}, you are already on the leaderboard.")
        except asyncio.TimeoutError:
                await ctx.send(f"{ctx.author.mention}, you took too long to respond.")

#Command to challenge other players for 2v2
@bot.command()
async def challenge(ctx):
        ranked_players = get_ranked_players()
        player_rank = next((i for i , (player_id, info) in enumerate(ranked_players, start=1) if player_id == str(ctx.author.id)), None)          
        if player_rank is None:
                await ctx.send("You are not in the ranking system. Use $join to enter.")
                return

        #If bot is paused
        global pause_mode
        if(pause_mode):
                await ctx.send("The bot is not accepting challenges at this moment")
                return

        nearby_players = get_nearby_players(player_rank)
        #Display potential partners
        if(ranking_diff):
                partner_message ="**Choose your partner:**\n"
                for rank, (player_id, info) in enumerate(nearby_players, start=max(1, player_rank - 3)):
                        partner_message += f"{rank}. {info['name']} - {info['elo']} ELO\n"
                await ctx.send(partner_message)
        await ctx.send("Mention the player you want as your partner")

        def check_partner(m):
                return m.author == ctx.author and m.mentions

        try:
                partner_msg = await bot.wait_for('message', check=check_partner,timeout = 60)
                partner_user_self = partner_msg.mentions[0]

                if str(partner_user_self.id) not in players:
                        await ctx.send(f"{partner_user_self.name} is not in the ranking system.")
                        return

                #Now prompt the user to choose two opponents
                if(ranking_diff):
                        challenge_message = "**Nearby players you can challenge:**\n"
                        for rank, (player_id, info) in enumerate(nearby_players, start=max(1, player_rank - 3)):
                                challenge_message += f"{rank}. {info['name']} - {info['elo']} ELO\n"
                        await ctx.send(challenge_message)
                await ctx.send("Mention the first player you want to challenge")

                def check_opponent(m):
                        return m.author == ctx.author and m.mentions

                opponent_msg_1 = await bot.wait_for('message', check=check_opponent, timeout = 60)
                challenged_user_1 = opponent_msg_1.mentions[0]

                if str(challenged_user_1.id) not in players:
                        await ctx.send(f"{challenged_user_1.name} is not in the ranking system.")
                        return

                await ctx.send("Mention the second player you want to challenge")
                opponent_msg_2 = await bot.wait_for('message', check=check_opponent, timeout = 60)
                challenged_user_2 = opponent_msg_2.mentions[0]

                if str(challenged_user_2.id) not in players:
                        await ctx.send(f"{challenged_user_2.name} is not in the ranking system")
                        return

                #Store active matches with consitent keys
                active_matches[str(ctx.author.id)] = {
                        'team_1':[str(ctx.author.id), str(partner_user_self.id)],
                        'team_2':[str(challenged_user_1.id), str(challenged_user_2.id)]
                }

                await ctx.send(f"{ctx.author.mention}/{partner_user_self.mention} vs {challenged_user_1.mention}/{challenged_user_2.mention}!") 
                        except discord.TimeoutError:
                                await ctx.send("You took too long to respond. Challenge canceled.")


@bot.command()
async def results(ctx, winner: discord.Member):
        #Retrieve the match where the user is a participant
        match = None
        for match_key, match_info in active_matches.items():
                if str(ctx.author.id) in match_info['team_1'] or str(ctx.author.id) in match_info['team_2']:
                        match=match_info
                        break

        if match is None:
                await ctx.send(f"{ctx.author.mention}, you are not in an active match.")
                return

        #Check if the winner is part of either team
        if winner.id not in[int(player) for player in match['team_1']] and winner.id not in [int(player) for player in  match['team_2']]:
                await ctx.send("The mentioned winner must be from the match participants.")
                return

        #Calculate team rating
        team_a_rating = sum(players[str(p)]['elo'] for p in match['team_1'])
        team_b_rating = sum(players[str(p)]['elo'] for p in match['team_2'])

        #Determine if the winning player is in team 1 or team 2
        team_a_won = False
        for player in match['team_1']:
                if player == str(winner.id):
                        team_a_won = True
                        break

        #Calculate ELO change
        elo_change = calculate_elo_change(team_a_rating, team_b_rating, team_a_won)

        #Update ELOs for Team A and Team B
        for player in match['team_1']:
                update_activity(str(player)) #Update their last active data
                if(team_a_won):
                        players[str(player)]['elo'] += int(elo_change * (1 - (players[str(player)]['elo'] / team_a_rating)))
                else:
                        players[str(player)]['elo'] -= int(elo_change * ((players[str(player)]['elo'] / team_a_rating)))

        for player in match['team_2']:
                update_activity(str(player)) #Update their last active data
                if(team_a_won):
                        players[str(player)]['elo'] -= int(elo_change * ((players[str(player)]['elo'] / team_b_rating)))
                else:
                        players[str(player)]['elo'] += int(elo_change * (1 - (players[str(player)]['elo'] / team_b_rating)))

        save_data()

        #Prepare output
        winners = [players[str(player)] for player in match['team_1']] if team_a_won else [players[str(player)] for player in match['team_2']]
        losers = [players[str(player)] for player in match['team_2']] if team_a_won else [players[str(player)] for player in match['team_1']]

        result_message = "ELO Updated\n--Winners--\n"
        for winner in winners:
                result_message += f"{winner['name']} - ELO: {winner['elo']}\n"

        result_message += "--Losers--\n"
        for loser in losers:
                result_message += f"{loser['name']} - ELO: {loser['elo']}\n"

        await ctx.send(result_message)

        #Clear the match after results are processed
        del active_matches[str(ctx.author.id)]

@bot.command()
async def cancel(ctx):
        user_id = str(ctx.author.id)

        #Check if the user is part of an active match
        match_found = None
        for match_id, match in active_matches.iteams():
                if user_id in match['team_1'] or user_id in match['team_2']:
                        match_found = match_id
                        break

        if(match_found):
                #Remove all players in the match from active_matches
                match = active_matches[match_found]
                all_players = match['team_1'] + match['team_2']

                #Remove each player involved froma ctive_matches
                for player in all_players:
                        if player in active_matches:
                                del active_matches[player]

                #Inform the user that the match has been canceled
                await ctx.send(f"Match canlled. All players in the match have been removed from active matches.")

                #optionally remove the match from the active matches (if stored with match_id)
                del active_matches[match_found]
        else:
                await ctx.send(f"{ctx.author.mention}, you are not in an active match.")

#Display Leaderboard with player rankings
@bot.command()
async def leaderboard(ctx):
    leaderboard_message = "Leaderboard:\n"
    ranked_players = get_ranked_players()  # Get sorted list of players

    # Enumerate through ranked players to add rankings (1, 2, 3, etc.)
    for rank, (user_id, data) in enumerate(ranked_players, start=1):
        leaderboard_message += f"{rank}. {data['name']} - ELO: {data['elo']}\n"

    await ctx.send(leaderboard_message)

#Display people's Activity
@bot.command()
async def activity(ctx):
        user_id = str(ctx.author.id)

        if user_id not in players:
                await ctx.send("You are not in the ranking system. Use '$join' to enter")
                return

        #Get last game time
        last_game_time_str = players[user_id].get('last_game')

        if last_game_time_str:
                last_game_time = datetime.fromisoformat(last_game_time_str)
                current_time = datetime.now()

                time_since_last_game = current_time - last_game_time
                decay_start_time = last_game_time + timedelta(days=DECAY_PERIOD_DAYS)

                if time_since_last_game >= timedelta(days=DECAY_PERIOD_DAYS):
                        await ctx.send(f"{players[user_id]['name']}, your ELO is already decaying due to inactivity.")
                else:
                        time_until_decay = decay_start_time - current_time
                        days_until_decay = time_until_decay.days
                        hours_until_decay, remainder = divmod(time_until_decay.seconds, 3600)
                        await ctx.send(f"{players[user_id]['name']}, you have {days_until_decay} day(s) and {hours_until_decay} hour(s) until ELO decay starts.") 

#Admin can override a member's ELO
@bot.command()
@commands.has_permissions(administrator=True)
async def override(ctx, member: discord.Member, new_elo: int):
        players[str(member.id)]['elo'] = new_elo
        save_data()
        await ctx.send(f"{member.name}'s ELO has been overriden to {new_elo}.")

#Admin can remove a player from the leaderboard
@bot.command()
@commands.has_permissions(administrator=True)
async def remove(ctx, user: discord.Member):
        if str(user.id) in players:
                del players[str(user.id)]
                save_data()
                await ctx.send(f"{user.mention} has been removed from the leaderboard.")
        else:
                await ctx.send(f"{user.mention} is not on the leaderboard.")

#Admin can pause the bot
@bot.command()
@commands.has_permissions(administrator=True)
async def pause(ctx):
        global pause_mode
        pause_mode = True
        await ctx.send("The bot is now paused and challenges will not be accepted")

#Admin can resume the bot
@bot.command()
@commands.has_permissions(administrator=True)
async def resume(ctx):
        global pause_mode
        pause_mode = False
        await ctx.send("The bot has been resumed and will now take challenges")

#Toggle ELO Decay
@bot.command()
@commands.has_permissions(administrator=True)
async def toggle_decay(ctx):
        global pause_elo_decay
        if(pause_elo_decay):
                pause_elo_decay = False
                await ctx.send("ELO decay is active")
        else:
                pause_elo_decay = True
                await ctx.send("ELO decay has been paused")

#For first time use to set everyone's last time played to the current time
@bot.command()
@commands.has_permissions(administrator=True)
async def start_decay(ctx):
        current_time = datetime.now().isoformat()
        for user_id in players:
                players[user_id]['last_game'] = current_time
        save_data()
        await ctx.send("All players' last game time has been reset to today.")

#Admin can add 15 to a user ELO if they're early
@bot.command()
@commands.has_permissions(administrator=True)
async def early(ctx, member: discord.Member):
        if str(member.id) in players:
                players[str(member.id)]['elo'] += 15
                save_data()
                await ctx.send(f"{member.name} was on time. ELO: {players[str(member.id)]['elo']}")
        else:
                await ctx.send(f"{member.name} is not on the leaderboard")

@tasks.loop(time=decay_time)
async def apply_elo_decay():
    now = datetime.now()
    if not pause_elo_decay:
        for player_id, data in players.items():
            last_game_time = datetime.fromisoformat(data.get('last_game', now.isoformat()))
            if now - last_game_time > INACTIVITY_THRESHOLD:
                old_elo = data['elo']
                data['elo'] = max(1, int(data['elo'] * DECAY_FACTOR))
                player_name = data['name']
                # Send a message when a player's ELO decays
                channel = bot.get_channel(CHAT_ID)
                if chat:
                    await chat.send(f"{player_name}'s ELO decayed from {old_elo} to {data['elo']} due to inactivity.")
            save_data()

bot.run(BOT_TOKEN)
