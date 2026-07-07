-- init.lua — Pac's Arcade Luanti mod (SCAFFOLDING / STUB) 💜
--
-- The voxel-verse front-end into the Federated Knowledge Engine. This mod does NOT own world
-- state: it POSTs world actions to the node-local `state-sync` service (HOT, :8082), which
-- translates them into DB-2 writes so the Luanti world and the MUD stay in lock-step. It also
-- forwards in-game chat to `matrix-bridge` (COLD, :8084), off the hot path.
--
-- Tier: HOT. Keep everything here node-local and snappy. The HTTP calls target localhost
-- services only; none of them cross the network from the mod's perspective.
--
-- TODO: operator must whitelist this mod for HTTP in minetest.conf:  secure.http_mods = pacsarcade

local MODNAME = minetest.get_current_modname()

-- Node-local service endpoints. These are other containers on the same box.
-- TODO: make these configurable via minetest.settings (settingtypes.txt) instead of hardcoding.
local STATE_SYNC_URL   = "http://state-sync:8082"
local MATRIX_BRIDGE_URL = "http://matrix-bridge:8084"
local WORLD_ID = "default"   -- TODO: derive the realm/world id from server config.

-- Request the sandboxed HTTP API (only granted if the mod is whitelisted). May be nil.
local http = minetest.request_http_api and minetest.request_http_api() or nil
if not http then
    minetest.log("warning", "["..MODNAME.."] No HTTP API — add '"..MODNAME.."' to secure.http_mods. "
        .. "Levers will be inert until then, fren.")
end

-- --------------------------------------------------------------------------- --
-- The "logic gate lever" node                                                 --
-- Right-clicking it POSTs a world event to state-sync, which mutates DB-2 and  --
-- returns the resulting state. The SAME state a `pull lever` in the MUD makes. --
-- --------------------------------------------------------------------------- --

minetest.register_node(MODNAME..":logic_gate_lever", {
    description = "Logic Gate Lever (syncs to the shared world state)",
    -- TODO: real textures/mesh; this is a placeholder so the node registers.
    tiles = { "default_steel_block.png" },
    groups = { cracky = 2, oddly_breakable_by_hand = 1 },

    -- on_rightclick fires when a fren pulls the lever.
    on_rightclick = function(pos, node, clicker)
        local player_name = clicker and clicker:get_player_name() or "unknown"
        local object_id = minetest.pos_to_string(pos)   -- stable id for this specific lever

        if not http then
            minetest.chat_send_player(player_name, "The lever is stuck — the verse can't reach state-sync yet.")
            return
        end

        -- Translate the world action into a state-sync event.
        local body = minetest.write_json({
            world = WORLD_ID,
            actor = player_name,
            object_id = object_id,
            event = "lever_pulled",
            pos = { x = pos.x, y = pos.y, z = pos.z },
            meta = {},
        })

        -- POST /event/luanti — HOT, node-local. The async callback just reflects returned state;
        -- we never block the game step waiting on it.
        http.fetch({
            url = STATE_SYNC_URL .. "/event/luanti",
            method = "POST",
            extra_headers = { "Content-Type: application/json" },
            data = body,
            timeout = 2,   -- node-local; if it can't answer fast, degrade, never hang.
        }, function(res)
            -- TODO: parse res.data (the resulting WorldState) and update the visible node/door
            --       state to match DB-2 (e.g. swing a linked door open). For now, just log.
            if res.succeeded then
                minetest.log("action", "["..MODNAME.."] lever "..object_id.." synced.")
            else
                minetest.chat_send_player(player_name, "The Archivist notes the lever didn't quite catch…")
            end
        end)
    end,
})


-- --------------------------------------------------------------------------- --
-- Chat forwarding → matrix-bridge (COLD, async)                               --
-- register_on_chat_message runs for every in-game chat line. We forward it to  --
-- the Matrix bridge and RETURN FALSE so normal in-game chat still happens.     --
-- --------------------------------------------------------------------------- --

minetest.register_on_chat_message(function(name, message)
    if not http then
        return false   -- no bridge available; let normal chat proceed untouched.
    end

    -- Fire-and-forget: hand the line to matrix-bridge and immediately move on. COLD tier —
    -- delivery to Matrix is background/eventually-consistent and NEVER blocks the game.
    http.fetch({
        url = MATRIX_BRIDGE_URL .. "/relay/from-game",
        method = "POST",
        extra_headers = { "Content-Type: application/json" },
        data = minetest.write_json({
            world = WORLD_ID,
            actor = name,
            text = message,
            room = "#"..WORLD_ID..":matrix",   -- TODO: real room alias mapping.
        }),
        timeout = 2,
    }, function(_res)
        -- TODO: optional: surface delivery failures in a debug channel. Never to gameplay.
    end)

    return false   -- IMPORTANT: don't swallow the message; normal chat still shows in-world.
end)

minetest.log("action", "["..MODNAME.."] loaded — voxel front-end of the Federated Knowledge Engine 💜")
