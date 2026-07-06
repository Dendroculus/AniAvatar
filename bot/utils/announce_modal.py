import discord
import logging

class AnnounceModal(discord.ui.Modal):
    def __init__(self, channel: discord.TextChannel, author: discord.Member, mention: bool):
        super().__init__(title="📢 Create Announcement")
        self.channel = channel
        self.author = author
        self.mention = mention

        """
        TextInput rationale:
        - paragraph style enables multi-line announcements suitable for detailed notices.
        - max_length is set to 4000 to align with Discord's message limits and prevent
          excessively long submissions that would inevitably fail when sending.
        - required=True enforces that the admin provides message content before submission.
        """
        self.message = discord.ui.TextInput(
            label="Announcement Message",
            style=discord.TextStyle.paragraph,
            placeholder="Type your announcement here",
            required=True,
            max_length=4000
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        """
        Send the announcement composed in the modal.

        Behavior notes:
        - The interaction is deferred ephemerally so the modal UX closes immediately for the user
          and follow-up messages (success or failure) can be sent privately to the invoker.
        - The announcement content is constructed with an optional everyone mention prefix.
        - allowed_mentions is explicitly configured to prevent accidental pings from any mention-like
          substrings contained in the message body.
        - Exceptions are not swallowed; the raw exception is reported back to the admin ephemerally
          to aid in diagnosing permission issues, invalid channel types, or rate limit responses.
        """
        await interaction.response.defer(ephemeral=True)

        content = f"{'@everyone\n' if self.mention else ''}{self.message.value}"

        try:
            await self.channel.send(
                content=content,
                allowed_mentions=discord.AllowedMentions(everyone=self.mention)
            )
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Failed to send announcement: {e}", ephemeral=True)
        except Exception as e:
            logging.getLogger("announce_modal").error(f"Unexpected error sending announcement: {e}")
            await interaction.followup.send(f"❌ Failed to send announcement: {e}", ephemeral=True)