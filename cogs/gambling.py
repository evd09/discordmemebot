# cogs/gambling.py
import discord
import random
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Literal, List, Optional, Callable, Awaitable
import discord
from discord import Embed
from discord import app_commands, Interaction
from discord.ui import View, button, Button
from discord.ext import commands, tasks
from helpers.store import Store

log = logging.getLogger(__name__)

def gambling_enabled():
    async def predicate(interaction: Interaction) -> bool:
        cog = interaction.client.get_cog("Gamble")
        if cog is None:
            raise app_commands.CheckFailure("❌ Gambling is not available.")
        guild_id = str(interaction.guild_id)
        if not await cog.store.is_gambling_enabled(guild_id):
            raise app_commands.CheckFailure("❌ Gambling is disabled in this server.")
        return True
    return app_commands.check(predicate)

class FlipView(View):
    def __init__(
        self,
        amount: int,
        store: Store,
        charge: Callable[[str,int,str], Awaitable[None]],
        payout: Callable[[str,int,str], Awaitable[None]],
        coin_name: str
    ):
        super().__init__(timeout=30)
        self.amount    = amount
        self.store     = store
        self._charge   = charge
        self._payout   = payout
        self.coin_name = coin_name
        # will be set by the command after sending
        self.message: discord.Message | None = None

    @button(label="Heads", style=discord.ButtonStyle.primary)
    async def heads(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, "heads")

    @button(label="Tails", style=discord.ButtonStyle.secondary)
    async def tails(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, "tails")

    async def _resolve(self, interaction: Interaction, guess: str):
        # do the coin flip
        result = random.choice(["heads", "tails"])
        uid = str(interaction.user.id)

        if guess == result:
            await self._payout(uid, self.amount, f"Flip win ({result})")
            text = (
                f"🎉 It was **{result}** — "
                f"you win **{self.amount}** {self.coin_name}!"
            )
        else:
            await self._charge(uid, self.amount, f"Flip loss ({result})")
            text = (
                f"😢 It was **{result}** — "
                f"you lose **{self.amount}** {self.coin_name}."
            )

        # disable all buttons
        for btn in self.children:
            btn.disabled = True

        await interaction.response.edit_message(content=text, view=self)
    
    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: Interaction):
        log.error(
            "View error in %s for user %s: %s",
            self.__class__.__name__,
            interaction.user.id,
            error,
            exc_info=True
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Oops, that action failed. Please try again.",
                ephemeral=True
            )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            log.exception("Failed to disable buttons on timeout in %s", self.__class__.__name__)

# ─── High-Low View ────────────────────────────────────────────────────────────
class HighLowView(View):
    def __init__(
        self,
        amount: int,
        store: Store,
        charge: Callable[[str, int, str], Awaitable[None]],
        payout: Callable[[str, int, str], Awaitable[None]],
        coin_name: str
    ):
        super().__init__(timeout=30)
        self.amount    = amount
        self.store     = store
        self._charge   = charge
        self._payout   = payout
        self.coin_name = coin_name

    @button(label="Higher", style=discord.ButtonStyle.primary)
    async def higher(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, "higher")

    @button(label="Lower", style=discord.ButtonStyle.secondary)
    async def lower(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, "lower")

    async def _resolve(self, interaction: Interaction, choice: str):
        deck = list(range(2, 15))
        a, b = random.choice(deck), random.choice(deck)
        win  = (choice == "higher" and b > a) or (choice == "lower" and b < a)
        uid  = str(interaction.user.id)

        if win:
            await self._payout(uid, self.amount, f"HighLow win ({choice})")
            text = f"First {a}, then {b} — you win **{self.amount}** {self.coin_name}!"
        else:
            await self._charge(uid, self.amount, f"HighLow loss ({choice})")
            text = f"First {a}, then {b} — you lose **{self.amount}** {self.coin_name}."

        for child in self.children:
            child.disabled = True
            child.style    = discord.ButtonStyle.secondary
        await interaction.response.edit_message(content=text, view=self)

    async def on_error(self, interaction: Interaction, error: Exception, item: discord.ui.Item):
        log.error(
            "View error in %s for user %s: %s",
            self.__class__.__name__,
            interaction.user.id,
            error,
            exc_info=True
        )
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Oops, that action failed. Please try again.", ephemeral=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
            child.style    = discord.ButtonStyle.secondary


# ─── Roll View ────────────────────────────────────────────────────────────────
class RollView(View):
    def __init__(
        self,
        amount: int,
        store: Store,
        charge: Callable[[str, int, str], Awaitable[None]],
        payout: Callable[[str, int, str], Awaitable[None]],
        coin_name: str
    ):
        super().__init__(timeout=30)
        self.amount    = amount
        self.store     = store
        self._charge   = charge
        self._payout   = payout
        self.coin_name = coin_name

    @button(label="2", style=discord.ButtonStyle.primary)
    async def two(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, 2)
    @button(label="3", style=discord.ButtonStyle.primary)
    async def three(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, 3)
    @button(label="4", style=discord.ButtonStyle.primary)
    async def four(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, 4)
    @button(label="5", style=discord.ButtonStyle.primary)
    async def five(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, 5)
    @button(label="6", style=discord.ButtonStyle.success)
    async def six(self, interaction: Interaction, button: Button):
        await self._resolve(interaction, 6)

    async def _resolve(self, interaction: Interaction, target: int):
        roll = random.randint(1, 6)
        odds = (7 - target) / 6
        uid  = str(interaction.user.id)

        if roll >= target:
            win = int(self.amount * odds)
            await self._payout(uid, win, f"Roll win (≥{target})")
            text = f"🎲 Rolled **{roll}** — you win **{win}** {self.coin_name}!"
        else:
            # tag losses as "Rolled X<Y" so winrate picks them up
            await self._charge(uid, self.amount, f"Roll loss (<{target})")
            text = f"🎲 Rolled **{roll}** — you lose **{self.amount}** {self.coin_name}."

        for child in self.children:
            child.disabled = True
            child.style    = discord.ButtonStyle.secondary
        await interaction.response.edit_message(content=text, view=self)

    async def on_error(self, error: Exception, item, interaction: Interaction):
        log.error(
            "View error in %s for user %s", self.__class__.__name__, interaction.user.id, exc_info=True
        )
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Oops, that action failed. Please try again.", ephemeral=True)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
            child.style    = discord.ButtonStyle.secondary

class CrashView(View):
    def __init__(
        self,
        interaction: Interaction,
        amount: int,
        store: Store,
        charge: Callable[[str,int,str], Awaitable[None]],
        payout: Callable[[str,int,str], Awaitable[None]],
        coin_name: str
    ):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.amount      = amount
        self.store       = store
        self._charge     = charge
        self._payout     = payout        
        self.coin_name   = coin_name
        # now from 0.0x up to 20.0x
        self.crash_point = random.uniform(0.0, 20.0)
        self.current     = 0.0
        self.ended       = False

        # add the cash-out button
        self.cash_btn = Button(label="Cash Out", style=discord.ButtonStyle.success)
        self.cash_btn.callback = self.cash_out_button
        self.add_item(self.cash_btn)

    async def start(self):
        # let Discord deliver the first message
        await asyncio.sleep(0.2)
        await self._run()

    async def _run(self):
        embed = Embed(
            title="Crash 🚀",
            description=f"Multiplier: **x{self.current:.2f}**\nClick **Cash Out** before it crashes!",
            color=discord.Color.blue()
        )
        await self.interaction.edit_original_response(embed=embed, view=self)

        # ramp up until crash or cash-out
        while not self.ended and self.current < self.crash_point:
            await asyncio.sleep(0.5)
            self.current += random.uniform(0.1, 0.5)

            embed.description = (
                f"Multiplier: **x{self.current:.2f}**\n"
                "Click **Cash Out** before it crashes!"
            )
            await self.interaction.edit_original_response(embed=embed, view=self)

        if not self.ended:
            # we hit the crash point
            self.ended = True
            # record a crash‐loss into winrate stats:
            uid = str(self.interaction.user.id)
            await self._charge(uid, self.amount, f"Crash loss x{self.crash_point:.2f}")
            for btn in self.children:
                btn.disabled = True

            user = self.interaction.user.display_name
            crash_embed = Embed(
                title="💥 Crashed!",
                description=(
                    f"The crash hit **x{self.crash_point:.2f}** — "
                    f"**{user}** lost **{self.amount}** {self.coin_name}."
                ),
                color=discord.Color.red()
            )
            await self.interaction.edit_original_response(embed=crash_embed, view=self)

    async def cash_out_button(self, interaction: Interaction):
        if self.ended:
            return await interaction.response.defer()

        # stop further updates
        self.ended = True
        self.cash_btn.disabled = True

        payout = int(self.amount * self.current)
        user = interaction.user.display_name
        win_embed = Embed(
            title="🏁 Cashed Out!",
            description=(
                f"**{user}** cashed out at **x{self.current:.2f}** — "
                f"won **{payout}** {self.coin_name}!"
            ),
            color=discord.Color.green()
        )

        # 1) update the original message
        await interaction.response.edit_message(embed=win_embed, view=self)

        # 2) record a crash‐win into winrate stats
        uid = str(interaction.user.id)
        await self._payout(uid, payout, f"Crash win x{self.current:.2f}")

        # 3) send ephemeral new-balance
        new_bal = await self.store.get_balance(uid)
        await interaction.followup.send(
            f"💰 Your new balance is **{new_bal}** {self.coin_name}.",
            ephemeral=True
        )

    async def on_error(self, error: Exception, item, interaction: Interaction):
        log.error("CrashView error for %s: %s", interaction.user.id, error, exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Something went wrong in the crash game.",
                ephemeral=True
            )

    async def on_timeout(self):
        # nobody cashed out in time
        self.ended = True
        for btn in self.children:
            btn.disabled = True

        timeout_embed = Embed(
            title="⌛ Crash Timed Out",
            description=(
                f"No cash-out before crash. You lose **{self.amount}** {self.coin_name}."
            ),
            color=discord.Color.red()
        )
        try:
            await self.interaction.edit_original_response(embed=timeout_embed, view=self)
        except Exception:
            log.exception("Failed to disable buttons on CrashView timeout")

class BlackjackView(discord.ui.View):
    def __init__(
        self,
        interaction: Interaction,
        bet_amount: int,
        store: Store,
        coin_name: str,
        auto_aces: bool = False
    ):
        super().__init__(timeout=120)
        self.interaction = interaction
        self.bet = bet_amount
        self.store = store
        self.coin_name = coin_name
        self.auto_aces = auto_aces

        # build & shuffle a 52-card deck
        self.deck = [1] * 4 + [10] * 16 + [v for v in range(2, 11) for _ in range(4)]
        random.shuffle(self.deck)

        # deal initial 2 cards each
        self.player = [self.deck.pop(), self.deck.pop()]
        self.dealer = [self.deck.pop(), self.deck.pop()]

        # helper for best “soft” score
        def best_score(cards: List[int]) -> int:
            total = sum(cards)
            # if you have an ace counted as 1 and can add 10 without busting…
            if 1 in cards and total + 10 <= 21:
                return total + 10
            return total
        self.best_score = best_score

        # if auto_aces, immediately adjust all aces
        if self.auto_aces:
            self.player = [best_score([c]) if c == 1 else c for c in self.player]

        # do we still have a raw ace (1) to choose?
        has_ace = any(c == 1 for c in self.player) and not self.auto_aces

        # disable hit/stand only if user must pick an ace
        self.hit_button.disabled   = has_ace
        self.stand_button.disabled = has_ace

        # enable ace-choice only when there’s an ace and manual mode
        self.ace1_button.disabled  = not has_ace
        self.ace11_button.disabled = not has_ace

    def embed(self, *, result: Optional[str]=None, bust: bool=False) -> discord.Embed:
        title = "🃏 Blackjack" if result is None else "🃏 Blackjack Result"
        ps = self.best_score(self.player)
        user = self.interaction.user.display_name
        if result is None:
            desc = (
                f"**{user}**'s hand: {self.player} — **{ps}**\n"
                f"Dealer: [{self.dealer[0]}, '?']\n\n"
            )
            if any(c == 1 for c in self.player) and not self.auto_aces:
                desc += "Choose Ace value, or Hit/Stand below."
            else:
                desc += "Hit to draw, Stand to hold."
        else:
            ds = self.best_score(self.dealer)
            desc = (
                f"{result}\n\n"
                f"Final — **{user}**: {self.player} ({ps}), Dealer: {self.dealer} ({ds})"
            )
        color = discord.Color.red() if bust or (result and "lose" in result) else discord.Color.green()
        return discord.Embed(title=title, description=desc, color=color)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary)
    async def hit_button(self, interaction, button):
        card = self.deck.pop()
        self.player.append(card)
        # if manual ace drawn
        if card == 1 and not self.auto_aces:
            await interaction.response.edit_message(embed=self.embed(), view=self)
            return
        score = self.best_score(self.player)
        if score > 21:
            user = interaction.user.display_name
            e = self.embed(
                result=f"😢 **{user}** loses {self.bet} {self.coin_name}.",
                bust=True
            )
            for b in self.children: b.disabled = True
            await interaction.response.edit_message(embed=e, view=self)
            await self.store.update_balance(str(interaction.user.id), -self.bet, "Blackjack loss")
        else:
            await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary)
    async def stand_button(self, interaction, button):
        # dealer draws to 17+
        while self.best_score(self.dealer) < 17:
            self.dealer.append(self.deck.pop())
        p, d = self.best_score(self.player), self.best_score(self.dealer)
        if p > 21 or (d <= 21 and d > p):
            user = interaction.user.display_name
            result, amt = f"😢 **{user}** loses {self.bet} {self.coin_name}.", -self.bet
        elif p == d:
            result, amt = "🤝 Push – it's a tie!", 0
        else:
            win = int(self.bet * (1.5 if p == 21 and len(self.player)==2 else 1))
            user = interaction.user.display_name
            result, amt = f"🎉 **{user}** wins {win} {self.coin_name}!", win
        e = self.embed(result=result)
        for b in self.children: b.disabled = True
        await interaction.response.edit_message(embed=e, view=self)
        if amt > 0:
            await self.store.update_balance(str(interaction.user.id), amt, "Blackjack win")

    @discord.ui.button(label="Use Ace as 1", style=discord.ButtonStyle.primary)
    async def ace1_button(self, interaction, button):
        idx = self.player.index(1)
        self.player[idx] = 1
        button.disabled = True
        self.ace11_button.disabled = True
        self.hit_button.disabled = False
        self.stand_button.disabled = False
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Use Ace as 11", style=discord.ButtonStyle.secondary)
    async def ace11_button(self, interaction, button):
        idx = self.player.index(1)
        self.player[idx] = 11
        button.disabled = True
        self.ace1_button.disabled = True
        self.hit_button.disabled = False
        self.stand_button.disabled = False
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def end(self, win: bool, multiple: float = 1.0):
        self.ended = True
        for btn in self.children:
            btn.disabled = True

        user = self.interaction.user.display_name
        uid  = str(self.interaction.user.id)
        if win:
            payout = int(self.amount * multiple)
            await self.store.update_balance(uid, payout, f"Blackjack win x{multiple}")
            result = f"🎉 **{user}** wins **{payout}** {self.coin_name}!"
            color  = discord.Color.green()
        else:
            await self.store.update_balance(uid, -self.amount, "Blackjack loss")
            result = f"😢 **{user}** loses {self.amount} {self.coin_name}."
            color  = discord.Color.red()

        e = discord.Embed(
            title="🃏 Blackjack Result",
            description=(
                f"{result}\n\n"
                f"Final hands — You: {self.player} ({self.score(self.player)}), "
                f"Dealer: {self.dealer} ({self.score(self.dealer)})"
            ),
            color=color
        )
        await self.message.edit(embed=e, view=self)

    async def on_error(self, error: Exception, item, interaction: Interaction):
        # log and notify the user
        log.error(
            "View error in %s for user %s: %s",
            self.__class__.__name__,
            interaction.user.id,
            error,
            exc_info=True
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Oops, that action failed. Please try again.",
                ephemeral=True
            )

    async def on_timeout(self):
        # disable any remaining buttons and edit
        for child in self.children:
            child.disabled = True
        try:
            await self.interaction.edit_original_response(view=self)
        except Exception:
            log.exception("Failed to disable buttons on timeout in %s", self.__class__.__name__)

class Gamble(commands.Cog):
    """Slash‐only gambling commands"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = Store()
        self.last_gamble_channel = None  # Track the last used gamble channel!

    def cog_unload(self):
        self.bot.loop.create_task(self.store.close())

    # 1) Define slash command group (no invoke_without_command here)
    gamble = app_commands.Group(
        name="gamble",
        description="Play one of seven games"
    )

    # 2) Register a nameless subcommand to act as the “help” / fallback
    @gambling_enabled()
    @gamble.command(
        name="help",
        description="Show help for all /gamble subcommands"
    )
    async def help(self, interaction: Interaction):
        """Show a list of available /gamble subcommands."""
        await interaction.response.send_message(
            "Available games: `flip`, `roll`, `slots`, `highlow`, `crash`, `blackjack`, `lottery`.\n"
            "Use `/gamble <game>` to play!",
            ephemeral=True
        )

    # shorthand for losing/winning bets
    async def _charge(self, uid: str, amt: int, reason: str):
        """Charge a losing bet with a game-specific reason."""
        await self.store.update_balance(uid, -amt, reason)      

    async def _payout(self, uid: str, amount: int, reason: str):
        await self.store.update_balance(uid, amount, reason)

    # ───── COG‐LEVEL ERROR HANDLER ────────────────────────────────────────────
    async def cog_app_command_error(
        self,
        interaction: Interaction,
        error: app_commands.AppCommandError
    ):
        # Catch our gambling‐disabled check
        if isinstance(error, app_commands.CheckFailure):
            return await interaction.response.send_message(
                str(error),
                ephemeral=True
            )

        # All other errors
        log.error(
            "Unhandled error in /gamble %s: %s",
            interaction.data.get("name"),
            error,
            exc_info=True
        )
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Something went wrong! Please try again later.",
                ephemeral=True
            )

    # ─── SUBCOMMANDS ───────────────────────────────────────────────────────────
    @gambling_enabled()
    @gamble.command(name="flip", description="Flip a coin: win on your guess.")
    @app_commands.describe(amount="How many coins to wager")
    async def flip(self, interaction: Interaction, amount: int):
        self.last_gamble_channel = interaction.channel.id
        uid  = str(interaction.user.id)
        bal  = await self.store.get_balance(uid)
        name = self.bot.config.COIN_NAME
        if amount > bal:
            return await interaction.response.send_message(
                f"❌ You need {amount} {name}, but have only {bal}.",
                ephemeral=True
            )
        await self.store.update_balance(uid, -amount, "Coin flip bet")
        view = FlipView(
            amount,
            self.store,
            charge=self._charge,
            payout=self._payout,
            coin_name=name
        )
        await interaction.response.send_message(
            f"🎲 Coin flip for **{amount}** {name}! Choose:",
            view=view,
            ephemeral=True
        )
        # capture the sent message so FlipView.on_timeout can edit it
        view.message = await interaction.original_response()

    @gambling_enabled()
    @gamble.command(name="highlow", description="Guess whether the next card is higher or lower.")
    @app_commands.describe(amount="How many coins to wager")
    async def highlow(self, interaction: Interaction, amount: int):
        self.last_gamble_channel = interaction.channel.id
        uid  = str(interaction.user.id)
        bal  = await self.store.get_balance(uid)
        name = self.bot.config.COIN_NAME
        if amount > bal:
            return await interaction.response.send_message(
                f"❌ You need {amount} {name}, but have only {bal}.",
                ephemeral=True
            )
        await self.store.update_balance(uid, -amount, "High-Low bet")
        view = HighLowView(
            amount,
            self.store,
            charge=self._charge,
            payout=self._payout,
            coin_name=name
        )
        await interaction.response.send_message(
            f"🃏 High-Low for **{amount}** {name}! Choose:", 
            view=view, ephemeral=True
        )

    @gambling_enabled()
    @gamble.command(name="roll", description="Roll a die: win if you meet or exceed your target.")
    @app_commands.describe(amount="How many coins to wager")
    async def roll(self, interaction: Interaction, amount: int):
        self.last_gamble_channel = interaction.channel.id
        uid  = str(interaction.user.id)
        bal  = await self.store.get_balance(uid)
        name = self.bot.config.COIN_NAME
        if amount > bal:
            return await interaction.response.send_message(
                f"❌ You need {amount} {name}, but have only {bal}.",
                ephemeral=True
            )
        await self.store.update_balance(uid, -amount, "Dice roll bet")
        view = RollView(
            amount,
            self.store,
            charge=self._charge,
            payout=self._payout,
            coin_name=name
        )
        await interaction.response.send_message(
            f"🎲 Dice roll for **{amount}** {name}! Pick a target (2–6):", 
            view=view, ephemeral=True
        )

    @gambling_enabled()
    @gamble.command(name="slots", description="Spin the slot machine.")
    @app_commands.describe(amount="How many coins to wager")
    async def slots(
        self,
        interaction: Interaction,
        amount: int
    ):
        self.last_gamble_channel = interaction.channel.id
        uid = str(interaction.user.id)
        bal = await self.store.get_balance(uid)
        name = self.bot.config.COIN_NAME
        if amount > bal:
            return await interaction.response.send_message(
                f"❌ You need {amount} {name}, but have only {bal}.",
                ephemeral=True
            )

        emojis = ["🍒","🍋","🔔","⭐"]
        reels = [random.choice(emojis) for _ in range(3)]
        counts = {e: reels.count(e) for e in set(reels)}
        mult = 5 if 3 in counts.values() else 2 if 2 in counts.values() else 0
        line = " ".join(reels)

        if mult:
            win = amount * mult
            await self._payout(uid, win, f"Slots win x{mult}")
            msg = f"{line}\n🎉 x{mult}, you win {win}!"
        else:
            await self._charge(uid, amount, "Slots loss")
            msg = f"{line}\n😢 no match — you lose {amount}."
        await interaction.response.send_message(msg, ephemeral=True)

    @gambling_enabled()
    @gamble.command(
        name="lottery",
        description="Enter the daily lottery (10 coins). Draw at 00:00 bot local time."
    )
    async def lottery(self, interaction: Interaction):
        self.last_gamble_channel = interaction.channel.id
        uid = str(interaction.user.id)
        cost = 10
        bal = await self.store.get_balance(uid)
        if bal < cost:
            return await interaction.response.send_message(
                f"❌ You need {cost} coins to enter.", ephemeral=True
            )

        # ensure they haven’t already entered today
        entered = await self.store.try_lottery(uid)
        if not entered:
            return await interaction.response.send_message(
                "❌ You’ve already entered today’s lottery.", ephemeral=True
            )

        # charge them and confirm
        await self.store.update_balance(uid, -cost, "Lottery entry")

        # show actual host timezone
        tz = datetime.now().astimezone().tzname() or "local time"

        await interaction.response.send_message(
            f"🎟️ You’re in! Lottery ticket bought for {cost} coins. Draw every day at 00:00 {tz}.",
            ephemeral=True
        )

    @gambling_enabled()
    @gamble.command(name="crash", description="Crash game: decide when to cash out before it crashes!")
    @app_commands.describe(amount="How many coins to wager")
    async def crash(self, interaction: Interaction, amount: int):
        self.last_gamble_channel = interaction.channel.id
        uid = interaction.user.id
        balance = await self.store.get_balance(str(uid))
        if amount > balance:
            return await interaction.response.send_message(
                f"❌ You need {amount} {self.bot.config.COIN_NAME}, but have {balance}.",
                ephemeral=True
            )

        # charge up front
        await self.store.update_balance(str(uid), -amount, "Crash bet")

        # send initial placeholder
        embed = Embed(
            title="Crash 🚀",
            description="Multiplier: **x1.00**\nClick **Cash Out** before it crashes!",
            color=discord.Color.blue()
        )
        view = CrashView(
            interaction,
            amount,
            self.store,
            charge=self._charge,
            payout=self._payout,
            coin_name=self.bot.config.COIN_NAME
        )
        # post into channel so everyone sees it
        await interaction.response.send_message(embed=embed, view=view)

        # grab the sent message object and start the loop
        msg = await interaction.original_response()
        await view.start()

    @gambling_enabled()
    @gamble.command(
        name="blackjack",
        description="Interactive blackjack: hit, stand, choose Ace value."
    )
    @app_commands.describe(
        amount="How many coins to wager (1–1000)",
        auto_aces="If true, bot auto-adjusts Aces (otherwise you pick)"
    )
    async def blackjack(
        self,
        interaction: Interaction,
        amount: app_commands.Range[int, 1, 1000],  # enforce 1 ≤ amount ≤ 1000
        auto_aces: bool = False
    ):
        self.last_gamble_channel = interaction.channel.id
        uid = str(interaction.user.id)
        bal = await self.store.get_balance(uid)
        if amount > bal:
            return await interaction.response.send_message(
                f"❌ You need {amount} coins but have {bal}.",
                ephemeral=True
            )

        # charge the bet
        await self.store.update_balance(uid, -amount, "Blackjack bet")

        view = BlackjackView(
            interaction,
            amount,
            self.store,
            self.bot.config.COIN_NAME,
            auto_aces=auto_aces
        )
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()

    @gambling_enabled()
    @gamble.command(name="history", description="Show your recent transactions")
    @app_commands.describe(limit="How many entries to show (max 20)")
    async def history(
        self,
        interaction: Interaction,
        limit: Optional[int] = 10
    ):
        self.last_gamble_channel = interaction.channel.id
        limit = max(1, min(limit, 20))
        uid   = str(interaction.user.id)
        rows  = await self.store.get_transactions(uid, limit)
        if not rows:
            return await interaction.response.send_message(
                "You have no transaction history yet.", ephemeral=True
            )

        # format each row: timestamp, +/-coins, reason
        lines = []
        for delta, reason, ts in rows:
            lines.append(f"<t:{ts}:f>  `{delta:+}`  {reason}")

        embed = discord.Embed(
            title="📜 Your Recent Transactions",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @gambling_enabled()
    @gamble.command(name="winrate", description="Show your win/loss counts per game")
    async def winrate(self, interaction: Interaction):
        self.last_gamble_channel = interaction.channel.id
        uid   = str(interaction.user.id)
        stats = await self.store.get_win_loss_counts(uid)

        lines = []
        for game, (wins, losses) in stats.items():
            total = wins + losses
            if total == 0:
                continue
            pct = wins / total * 100
            lines.append(f"**{game}** — {wins}/{total} wins ({pct:.1f}%)")

        embed = discord.Embed(
            title="📊 Your Win Rates",
            description="\n".join(lines) or "No gambling activity yet.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


    async def do_lottery_draw(self):
        entries = await self.store.get_today_lottery_entries()
        if not entries:
            return
        winner = random.choice(entries)
        await self.store.update_balance(winner['user_id'], amount=100, reason="Lottery win")
        await self.store.clear_lottery_entries()
        
        # Try last gamble channel
        channel = self.bot.get_channel(self.last_gamble_channel) if self.last_gamble_channel else None

        # Fallback: first text channel with permissions
        if channel is None or not channel.permissions_for(channel.guild.me).send_messages:
            main_guild = self.bot.guilds[0] if self.bot.guilds else None  # Safest fallback
            if main_guild and main_guild.text_channels:
                for ch in main_guild.text_channels:
                    if ch.permissions_for(main_guild.me).send_messages:
                        channel = ch
                        break

        user = self.bot.get_user(int(winner['user_id']))
        if channel:
            if user:
                await channel.send(f"🎉 Congrats {user.mention}! You won the daily lottery! 💰")
            else:
                await channel.send(f"🎉 We have a winner, but couldn't find their user ID: `{winner['user_id']}`.")
        else:
            print("No channel found to announce the lottery winner.")

        # Optionally DM the user
        if user:
            try:
                await user.send("You won the daily lottery! Congrats!")
            except Exception:
                pass

async def setup(bot):
    await bot.add_cog(Gamble(bot))
