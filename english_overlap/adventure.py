"""Deterministic battles and character growth from earned learning XP."""


def battle_progress(training_xp: int) -> dict:
    """Carry damage between enemies; rewards never feed back into damage.

    Four 40-HP slimes and an 80-HP boss form a 240-damage chapter.
    Deriving progress from saved activity makes reloads and retries harmless.
    """
    chapters, damage = divmod(max(0, training_xp), 240)
    defeated = chapters * 5
    reward_xp = chapters * 140
    names = ['ミントスライム', 'アクアスライム', 'アメジストスライム', 'フレイムスライム', 'ワードドラゴン']
    slot = 0
    while slot < 4 and damage >= 40:
        damage -= 40
        defeated += 1
        reward_xp += 20
        slot += 1
    max_hp = 80 if slot == 4 else 40
    return {
        'chapter': chapters + 1, 'encounter': defeated + 1,
        'defeated': defeated, 'bosses_defeated': chapters,
        'reward_xp': reward_xp, 'enemy_name': names[slot], 'enemy_style': slot,
        'is_boss': slot == 4, 'hp': max_hp - damage, 'max_hp': max_hp,
        'damage': damage, 'next_reward_xp': 60 if slot == 4 else 20,
    }


def character_progress(level: int) -> dict:
    stages = [(1, '見習い冒険者'), (3, '冒険者'), (5, 'クエストナイト'), (10, 'ことばの勇者')]
    index = max(i for i, (minimum, _) in enumerate(stages) if level >= minimum)
    next_stage = stages[index + 1] if index + 1 < len(stages) else None
    return {'stage': index, 'title': stages[index][1],
            'next_evolution_level': next_stage[0] if next_stage else None,
            'next_evolution_title': next_stage[1] if next_stage else None}
