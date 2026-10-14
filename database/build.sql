CREATE TABLE IF NOT EXISTS profiles (
	user_id integer PRIMARY KEY,
	display_name text DEFAULT NULL,
	level integer DEFAULT 1,
	exp integer DEFAULT 0,
	tokens integer DEFAULT 0,
	current_quest text DEFAULT NULL,
	current_quest_exp integer DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS cooldowns (
	user_id integer,
	command text,
	last_used real,
	PRIMARY KEY (user_id, command)
);