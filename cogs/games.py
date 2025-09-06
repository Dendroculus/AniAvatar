import discord
import asyncio
import aiohttp
from discord import app_commands
from discord.ext import commands
import random
import json
import os

class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data_path = os.path.join(os.path.dirname(__file__), "..", "data", "trivia.json")
        with open(self.data_path, "r", encoding="utf-8") as f:
            self.trivia_list = json.load(f)

    @commands.hybrid_command(name="animequiz", description="Start an anime trivia quiz.")
    @app_commands.describe(questions="Number of questions")
    @app_commands.choices(questions=[
        app_commands.Choice(name="5", value=5),
        app_commands.Choice(name="10", value=10),
        app_commands.Choice(name="15", value=15),
        app_commands.Choice(name="20", value=20),
    ])
    async def animequiz(self, ctx, questions: app_commands.Choice[int]):
        num_questions = questions.value
        quiz_questions = random.sample(self.trivia_list, min(num_questions, len(self.trivia_list)))
        score = 0

        profile_cog = self.bot.get_cog("Progression")  # Make sure this matches your cog name

        for idx, question in enumerate(quiz_questions, 1):
            # Build options
            other_answers = [q["answer"] for q in self.trivia_list if q["answer"] != question["answer"]]
            fake_options = random.sample(other_answers, k=min(3, len(other_answers)))
            options_list = fake_options + [question["answer"]]
            random.shuffle(options_list)
            options = [discord.SelectOption(label=opt, value=opt) for opt in options_list]

            embed = discord.Embed(title=f"Question {idx}/{num_questions}", description=question["question"])
            view = discord.ui.View()
            future = asyncio.get_event_loop().create_future()

            select = discord.ui.Select(placeholder="Choose an answer...", options=options)

            async def callback(interaction: discord.Interaction):
                if interaction.user != ctx.author:
                    await interaction.response.send_message("This is not your game!", ephemeral=True)
                    return
                future.set_result(interaction.data["values"][0])
                select.disabled = True
                await interaction.response.edit_message(view=view)

            select.callback = callback
            view.add_item(select)
            message = await ctx.send(embed=embed, view=view)

            try:
                selected = await asyncio.wait_for(future, timeout=15)
                if selected == question["answer"]:
                    score += 1
                    if profile_cog:

                        _, current_level = profile_cog.get_user(ctx.author.id, ctx.guild.id)
                        exp_reward = random.randint(5 + current_level * 2, 10 + current_level * 3)  
                        level, new_exp, leveled_up = profile_cog.add_exp(ctx.author.id, ctx.guild.id, exp_reward)
                        await ctx.send(f"✅ Correct! +{exp_reward} EXP")
                    else:
                        await ctx.send(f"✅ Correct! The answer is **{question['answer']}**.")
                else:
                    await ctx.send(f"❌ Wrong! The correct answer is **{question['answer']}**.")
            except asyncio.TimeoutError:
                select.disabled = True
                await message.edit(view=view)
                await ctx.send(f"⏰ Time's up! The correct answer was `{question['answer']}`.")

        await ctx.send(f"🏁 Quiz finished! You scored **{score}/{num_questions}**.")

    @commands.hybrid_command(name="guesscharacter", description="Guess a random popular anime character")
    async def guesscharacter(self, ctx):
        character = None
        source = "AniList"

        try:
            character = await self.fetch_anilist_character()
        except Exception as e:
            print(f"AniList API error: {e}")
            try:
                character = await self.fetch_jikan_character()
                source = "Jikan (MAL)"
            except Exception as e2:
                print(f"Jikan API error: {e2}")
                return await ctx.send("❌ Couldn't fetch characters from any API. Please try again later.")

        correct_name = character["name"]
        image = character["image"]
        anime_title = character["anime"]

        try:
            options_list = await self.get_character_options(correct_name, source)
        except Exception:
            return await ctx.send("❌ Failed to fetch options for the quiz. Please try again.")

        embed = discord.Embed(title="Guess the character!", description=f"From **{anime_title}**")
        embed.set_image(url=image)
        embed.set_footer(text=f"Source: {source}")

        view = discord.ui.View(timeout=60)
        view.correct_answer = correct_name
        view.anime_title = anime_title
        view.author_id = ctx.author.id

        select = discord.ui.Select(
            placeholder="Choose the correct character...",
            options=options_list
        )
        view.add_item(select)

        message = await ctx.send(embed=embed, view=view)

        select.callback = self.create_select_callback(view, message)

    async def fetch_anilist_character(self):
        query = '''
        query ($page: Int, $perPage: Int) {
            Page(page: $page, perPage: $perPage) {
                characters(sort: FAVOURITES_DESC) {
                    id
                    name { full }
                    image { large }
                    media { nodes { title { romaji } } }
                }
            }
        }
        '''
        random_page = random.randint(1, 20)
        variables = {"page": random_page, "perPage": 50}

        async with aiohttp.ClientSession() as session:
            async with session.post("https://graphql.anilist.co", json={"query": query, "variables": variables},
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    raise Exception(f"AniList returned status {resp.status}")
                data = await resp.json()
                characters = data.get("data", {}).get("Page", {}).get("characters", [])
                if not characters:
                    raise Exception("No characters found")
                character = random.choice(characters)
                anime_nodes = character.get("media", {}).get("nodes", [])
                anime_title = anime_nodes[0]["title"]["romaji"] if anime_nodes else "Unknown Anime"
                return {"name": character["name"]["full"], "image": character["image"]["large"], "anime": anime_title}

    async def fetch_jikan_character(self):
        page = random.randint(1, 10)
        url = f"https://api.jikan.moe/v4/top/characters?page={page}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    raise Exception(f"Jikan returned status {resp.status}")
                data = await resp.json()
                characters = data.get("data", [])
                if not characters:
                    raise Exception("No characters found")
                character = random.choice(characters)
                anime_nodes = character.get("anime", [])
                anime_title = anime_nodes[0]["title"] if anime_nodes else "Unknown Anime"
                return {"name": character["name"], "image": character["images"]["jpg"]["image_url"], "anime": anime_title}

    async def get_character_options(self, correct_name, source):
        options = [correct_name]
        if source == "AniList":
            wrong_options = await self.get_anilist_wrong_options(correct_name)
        else:
            wrong_options = await self.get_jikan_wrong_options(correct_name)
        options.extend(wrong_options)
        random.shuffle(options)
        return [discord.SelectOption(label=opt, value=opt) for opt in options]

    async def get_anilist_wrong_options(self, correct_name):
        query = '''
        query ($page: Int, $perPage: Int) {
            Page(page: $page, perPage: $perPage) {
                characters(sort: FAVOURITES_DESC) { name { full } }
            }
        }
        '''
        random_page = random.randint(1, 20)
        variables = {"page": random_page, "perPage": 50}
        async with aiohttp.ClientSession() as session:
            async with session.post("https://graphql.anilist.co", json={"query": query, "variables": variables},
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return self.get_fallback_wrong_options(correct_name)
                data = await resp.json()
                characters = data.get("data", {}).get("Page", {}).get("characters", [])
                wrong_names = [c["name"]["full"] for c in characters if c["name"]["full"] != correct_name]
                return random.sample(wrong_names, k=min(3, len(wrong_names)))

    async def get_jikan_wrong_options(self, correct_name):
        page = random.randint(1, 10)
        url = f"https://api.jikan.moe/v4/top/characters?page={page}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return self.get_fallback_wrong_options(correct_name)
                data = await resp.json()
                characters = data.get("data", [])
                wrong_names = [c["name"] for c in characters if c["name"] != correct_name]
                return random.sample(wrong_names, k=min(3, len(wrong_names)))

    def get_fallback_wrong_options(self, correct_name):
        fallback = ["Naruto Uzumaki", "Monkey D. Luffy", "Goku", "Light Yagami", "Eren Yeager", "Levi Ackerman",
                    "Saitama", "Edward Elric", "Spike Spiegel", "Lelouch Lamperouge", "Killua Zoldyck", "Gon Freecss"]
        wrong_names = [name for name in fallback if name != correct_name]
        return random.sample(wrong_names, k=min(3, len(wrong_names)))

    def create_select_callback(self, view, message):
        async def callback(interaction: discord.Interaction):
            if interaction.user.id != view.author_id:
                await interaction.response.send_message("This is not your game!", ephemeral=True)
                return
            selected = interaction.data["values"][0]
            correct_name = view.correct_answer
            anime_title = view.anime_title

            profile_cog = self.bot.get_cog("Progression")
            if selected == correct_name:
                if profile_cog:
                    _, current_level = profile_cog.get_user(interaction.user.id, interaction.guild.id)
                    exp_reward = random.randint(5 + current_level * 2, 10 + current_level * 3)
                    level, new_exp, leveled_up = profile_cog.add_exp(interaction.user.id, interaction.guild.id, exp_reward)
                    await interaction.response.send_message(f"✅ Correct! +{exp_reward} EXP")
                else:
                    await interaction.response.send_message(f"✅ Correct! It was **{correct_name}** from **{anime_title}**!")
            else:
                await interaction.response.send_message(f"❌ Wrong! The correct answer was **{correct_name}** from **{anime_title}**.")

            for item in view.children:
                if isinstance(item, discord.ui.Select):
                    item.disabled = True

            await message.edit(view=view)
        return callback
    
async def setup(bot):
    await bot.add_cog(Games(bot))
    print("📦 Loaded games cog.")
