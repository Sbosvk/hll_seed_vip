from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Iterable

import discord_webhook as discord
import httpx
import trio
import yaml
from humanize import naturaldelta, naturaltime
from loguru import logger

from hll_seed_vip.models import (
    BaseCondition,
    ConfigRequirementsType,
    ConfigType,
    ConfigVipRewardType,
    GameState,
    PlayerCountCondition,
    PlayTimeCondition,
    ServerConfig,
    ServerPopulation,
)


def with_backoff_retry():
    backoffs = (0, 1, 1.5, 2, 4, 8)

    def decorator(func):
        @wraps(func)
        async def wrapped(*args, **kwargs):
            server_url: str = args[1]
            for idx, backoff in enumerate(backoffs):
                try:
                    return await func(*args, **kwargs)
                except httpx.HTTPError as e:
                    logger.error(e)
                    logger.warning(
                        f"Retrying attempt {idx+1}/{len(backoffs)+1}, sleeping for {backoff} seconds for {server_url} function={func.__name__}"
                    )
                    await trio.sleep(backoff)
                    continue

        return wrapped

    return decorator


def load_config(path: Path) -> ServerConfig:
    with open(path) as fp:
        raw_config: ConfigType = yaml.safe_load(fp)
    logger.debug(f"{raw_config=}")

    requirements = ConfigRequirementsType(**raw_config["requirements"])
    vip_reward = ConfigVipRewardType(**raw_config["vip_reward"])

    return ServerConfig(
        base_url=raw_config["base_url"],
        discord_webhook=raw_config.get("discord_webhook"),  # type: ignore
        discord_seeding_complete_message=raw_config["discord_seeding_complete_message"],
        dry_run=raw_config["dry_run"],
        poll_time_seeding=raw_config["poll_time_seeding"],
        poll_time_seeded=raw_config["poll_time_seeded"],
        min_allies=requirements["min_allies"],
        max_allies=requirements["max_allies"],
        min_axis=requirements["min_axis"],
        max_axis=requirements["max_axis"],
        minimum_play_time=timedelta(**requirements["minimum_play_time"]),
        online_when_seeded=requirements["online_when_seeded"],
        cumulative_vip=vip_reward["cumulative"],
        vip_reward=timedelta(**vip_reward["timeframe"]),
        player_message=vip_reward["player_message"],
        nice_delta=vip_reward["nice_delta"],
        nice_date=vip_reward["nice_date"],
    )


def all_met(conditions: Iterable[BaseCondition]):
    return all(c.is_met() for c in conditions)


def check_population_conditions(config: ServerConfig, gamestate: GameState):
    """Return if the current player count is within min/max players for seeding"""
    player_count_conditions = [
        PlayerCountCondition(
            faction="allies",
            min_players=config.min_allies,
            max_players=config.max_allies,
            current_players=gamestate.num_allied_players,
        ),
        PlayerCountCondition(
            faction="axis",
            min_players=config.min_axis,
            max_players=config.max_axis,
            current_players=gamestate.num_axis_players,
        ),
    ]

    logger.debug(
        f"{player_count_conditions[0]}={player_count_conditions[0].is_met()} {player_count_conditions[1]}={player_count_conditions[1].is_met()} breaking",
    )
    if not all_met(player_count_conditions):
        return False

    return True


def check_player_conditions(
    config: ServerConfig, server_pop: ServerPopulation
) -> set[str]:
    """Return a set of steam IDs that meet seeding criteria"""
    return set(
        player.steam_id_64
        for player in server_pop.players.values()
        if PlayTimeCondition(
            min_time_secs=int(config.minimum_play_time.total_seconds()),
            current_time_secs=player.current_playtime_seconds,
        ).is_met()
    )


def is_seeded(config: ServerConfig, gamestate: GameState) -> bool:
    """Return if the server has enough players to be out of seeding"""
    return (
        gamestate.num_allied_players >= config.max_allies
        and gamestate.num_axis_players >= config.max_axis
    )


def calc_vip_expiration_timestamp(
    config: ServerConfig, expiration: datetime | None, from_time: datetime
) -> datetime:
    """Return the players new expiration date accounting for reward/existing timestamps"""
    if expiration is None:
        timestamp = from_time + config.vip_reward
        return timestamp

    if config.cumulative_vip:
        return expiration + config.vip_reward
    else:
        # Don't step on the old expiration if it's longer than the new one
        timestamp = from_time + config.vip_reward
        if timestamp < expiration:
            return expiration
        else:
            return timestamp


def collect_steam_ids(
    config: ServerConfig,
    players: ServerPopulation,
    cum_steam_ids: set[str],
) -> set[str]:
    player_conditions_steam_ids = check_player_conditions(
        config=config, server_pop=players
    )

    if config.online_when_seeded:
        cum_steam_ids = set(player_conditions_steam_ids)
    else:
        cum_steam_ids |= player_conditions_steam_ids

    return cum_steam_ids


def format_player_message(
    message: str,
    vip_reward: timedelta,
    vip_expiration: datetime,
    nice_delta: bool = True,
    nice_date: bool = True,
) -> str:
    if nice_delta:
        delta = naturaldelta(vip_reward)
    else:
        delta = vip_reward

    if nice_date:
        date = naturaltime(vip_expiration)
    else:
        date = vip_expiration.isoformat()

    return message.format(vip_reward=delta, vip_expiration=date)


def make_seed_announcement_embed(
    message: str | None,
    current_map: str,
    time_remaining: str,
    num_axis_players: int,
    num_allied_players: int,
) -> discord.DiscordEmbed | None:
    if not message:
        return

    embed = discord.DiscordEmbed(title=message)
    embed.add_embed_field(name="Current Map", value=current_map)
    embed.add_embed_field(name="Time Remaining", value=time_remaining)
    embed.add_embed_field(
        name="Players Per Team", value=f"{num_allied_players} : {num_allied_players}"
    )

    return embed


def format_vip_reward_name(player_name: str):
    return f"{player_name} - HLL Seed VIP"
