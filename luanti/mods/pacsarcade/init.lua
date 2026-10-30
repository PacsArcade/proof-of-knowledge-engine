-- init.lua — Pac's Arcade Luanti mod (SCAFFOLDING / STUB) 💜
--
-- The voxel-verse front-end into Proof of Knowledge Engine (P.O.K.E.). This mod does NOT own world
-- state: it POSTs world actions to the node-local `state-sync` service (HOT, :8082), which
-- translates them into DB-2 writes so the Luanti world and the MUD stay in lock-step. It also
-- forwards in-game chat to `matrix-bridge` (COLD, :8084), off the hot path.
--
-- Tier: HOT. Keep everything here node-local and snappy. The HTTP calls target localhost
-- services only; none of them cross the network from the mod's perspective.
--
-- TODO: operator must whitelist this mod for HTTP in minetest.conf:  secure.http_mods = pacsarcade

local MODNAME = minetest.get_current_modname()

-- Node-local service endpoints. Defaults are the compose service names; a dev box on the host
-- network overrides them in minetest.conf:
--   pacsarcade.state_sync_url = http://127.0.0.1:5212
--   pacsarcade.matrix_bridge_url = http://127.0.0.1:8084
--   pacsarcade.world_id = default
--   pacsarcade.lever_object_id = vault_lever   (all levers share one object; "" = one per position)
--   pacsarcade.dev_hooks = true                (file trigger + selftest lever, DEV ONLY)
local S = minetest.settings
local STATE_SYNC_URL    = S:get("pacsarcade.state_sync_url")    or "http://state-sync:8082"
local MATRIX_BRIDGE_URL = S:get("pacsarcade.matrix_bridge_url") or "http://matrix-bridge:8084"
local WORLD_ID          = S:get("pacsarcade.world_id")          or "default"
local LEVER_OBJECT_ID   = S:get("pacsarcade.lever_object_id")   or ""
local DEV_HOOKS         = S:get_bool("pacsarcade.dev_hooks", false)
local POLL_INTERVAL     = 1.0

-- Request the sandboxed HTTP API (only granted if the mod is whitelisted). May be nil.
local http = minetest.request_http_api and minetest.request_http_api() or nil
if not http then
    minetest.log("warning", "["..MODNAME.."] No HTTP API - add '"..MODNAME.."' to secure.http_mods. "
        .. "Levers will be inert until then, fren.")
end

-- --------------------------------------------------------------------------- --
-- The "logic gate lever" node (two visual states: off and on)                  --
-- Right-clicking it POSTs a world event to state-sync, which mutates DB-2 and  --
-- returns the resulting state. The SAME state a `pull lever` in the MUD makes. --
-- The node then follows the shared state, and a poll keeps it following changes --
-- made from the MUD side.                                                       --
-- --------------------------------------------------------------------------- --

local LEVER_OFF = MODNAME..":logic_gate_lever"
local LEVER_ON  = MODNAME..":logic_gate_lever_on"

local function object_id_for(pos)
    if LEVER_OBJECT_ID ~= "" then return LEVER_OBJECT_ID end
    return minetest.pos_to_string(pos)   -- stable id for this specific lever
end

-- Known lever positions (rebuilt from the map by the LBM below). key = pos hash.
local levers = {}

local function apply_state(pos, on)
    local node = minetest.get_node_or_nil(pos)
    if not node then return end
    local want = on and LEVER_ON or LEVER_OFF
    if node.name ~= want and (node.name == LEVER_ON or node.name == LEVER_OFF) then
        minetest.swap_node(pos, { name = want, param1 = node.param1, param2 = node.param2 })
    end
    minetest.get_meta(pos):set_string("infotext",
        "Logic Gate Lever: " .. (on and "ON" or "OFF") .. " (shared with the MUD)")
end

local function state_of(res, object_id)
    if not (res and res.succeeded and res.data) then return nil end
    local parsed = minetest.parse_json(res.data)
    if type(parsed) ~= "table" or type(parsed.state) ~= "table" then return nil end
    return parsed.state[object_id] == "on"
end

-- Pull the lever at pos as `player_name`. Used by right-click AND the dev test hook, so the
-- test exercises the real code path. The outcome arrives async.
local function pull_lever(pos, player_name)
    local object_id = object_id_for(pos)

    if not http then
        minetest.chat_send_player(player_name, "The lever is stuck - the verse can't reach state-sync yet.")
        return
    end

    local body = minetest.write_json({
        world = WORLD_ID,
        actor = player_name,
        object_id = object_id,
        event = "lever_pulled",
        pos = { x = pos.x, y = pos.y, z = pos.z },
        -- no `meta`: an empty Lua table serializes to [] and state-sync expects an object.
    })

    -- POST /event/luanti - HOT, node-local. Async: we never block the game step on it.
    http.fetch({
        url = STATE_SYNC_URL .. "/event/luanti",
        method = "POST",
        extra_headers = { "Content-Type: application/json" },
        data = body,
        timeout = 2,   -- node-local; if it can't answer fast, degrade, never hang.
    }, function(res)
        local on = state_of(res, object_id)
        if on ~= nil then
            apply_state(pos, on)
            minetest.log("action", "["..MODNAME.."] lever "..object_id.." pulled by "..player_name
                .." -> "..(on and "on" or "off"))
        else
            minetest.chat_send_player(player_name, "The Archivist notes the lever didn't quite catch...")
            minetest.log("warning", "["..MODNAME.."] lever POST failed: code "..tostring(res and res.code))
        end
    end)
end

local lever_def = {
    description = "Logic Gate Lever (syncs to the shared world state)",
    -- TODO: real textures/mesh; placeholders so the nodes register. Off = steel, on = gold.
    tiles = { "default_steel_block.png" },
    groups = { cracky = 2, oddly_breakable_by_hand = 1 },
    on_construct = function(pos) levers[minetest.hash_node_position(pos)] = pos end,
    on_destruct  = function(pos) levers[minetest.hash_node_position(pos)] = nil end,
    on_rightclick = function(pos, node, clicker)
        pull_lever(pos, clicker and clicker:get_player_name() or "unknown")
    end,
}
minetest.register_node(LEVER_OFF, lever_def)

local on_def = {}
for k, v in pairs(lever_def) do on_def[k] = v end
on_def.tiles = { "default_gold_block.png" }
on_def.light_source = 8
on_def.groups = { cracky = 2, oddly_breakable_by_hand = 1, not_in_creative_inventory = 1 }
on_def.drop = LEVER_OFF
minetest.register_node(LEVER_ON, on_def)

-- After a restart, re-learn where the levers are.
minetest.register_lbm({
    label = "pacsarcade: track levers",
    name = MODNAME..":track_levers",
    nodenames = { LEVER_OFF, LEVER_ON },
    run_at_every_load = true,
    action = function(pos) levers[minetest.hash_node_position(pos)] = pos end,
})

-- Poll the shared state so a lever pulled in the MUD swings here. One GET per distinct object.
local poll_acc = 0
minetest.register_globalstep(function(dtime)
    poll_acc = poll_acc + dtime
    if poll_acc < POLL_INTERVAL or not http then return end
    poll_acc = 0
    local by_object = {}
    for _, pos in pairs(levers) do
        local id = object_id_for(pos)
        by_object[id] = by_object[id] or {}
        table.insert(by_object[id], pos)
    end
    for id, plist in pairs(by_object) do
        http.fetch({
            url = STATE_SYNC_URL .. "/state/" .. WORLD_ID .. "/" .. minetest.urlencode(id),
            method = "GET",
            timeout = 2,
        }, function(res)
            local on = state_of(res, id)
            if on == nil then return end
            for _, pos in ipairs(plist) do
                local node = minetest.get_node_or_nil(pos)
                if node and ((node.name == LEVER_ON) ~= on) then
                    apply_state(pos, on)
                    minetest.log("action", "["..MODNAME.."] lever "..id.." followed shared state -> "
                        ..(on and "on" or "off"))
                end
            end
        end)
    end
end)

-- --------------------------------------------------------------------------- --
-- DEV HOOKS (pacsarcade.dev_hooks = true). Never enable on a public server.     --
-- Places a lever at a fixed spot and lets a file in the world dir drive it, so a --
-- headless test can "right-click" without a graphical client.                    --
--   <world>/pa_trigger  containing the word "pull" -> runs the lever's real       --
--                        on_rightclick with a fake player named selftest-bot.     --
-- Reading the file needs the insecure environment (pacsarcade is trusted). The    --
-- file is emptied (not removed) after each read.                                  --
-- --------------------------------------------------------------------------- --
if DEV_HOOKS then
    local ie = minetest.request_insecure_environment()
    local wp = minetest.get_worldpath()
    local test_pos = { x = 0, y = 10, z = 0 }

    minetest.after(2, function()
        minetest.emerge_area(vector.subtract(test_pos, 2), vector.add(test_pos, 2), function(_, _, remaining)
            if remaining > 0 then return end
            local n = minetest.get_node(test_pos)
            if n.name ~= LEVER_OFF and n.name ~= LEVER_ON then
                minetest.set_node(test_pos, { name = LEVER_OFF })
            end
            levers[minetest.hash_node_position(test_pos)] = test_pos
            minetest.log("action", "["..MODNAME.."] dev selftest lever at "..minetest.pos_to_string(test_pos))
        end)
    end)

    local fake = { get_player_name = function() return "selftest-bot" end }
    local acc = 0
    minetest.register_globalstep(function(dtime)
        acc = acc + dtime
        if acc < 0.5 or not ie then return end
        acc = 0
        local path = wp .. "/pa_trigger"
        local f = ie.io.open(path, "r")
        if not f then return end
        local txt = f:read("*a"); f:close()
        if txt == "" then return end
        local w = ie.io.open(path, "w")
        if w then w:close() end
        if txt:find("tp") then
            -- Move the selftest lever in front of the first player and face them at it.
            for _, pl in ipairs(minetest.get_connected_players()) do
                local pp = vector.round(pl:get_pos())
                minetest.set_node({x = pp.x, y = pp.y, z = pp.z + 1}, { name = "air" })
                minetest.set_node({x = pp.x, y = pp.y + 1, z = pp.z + 1}, { name = "air" })
                minetest.remove_node(test_pos)
                levers[minetest.hash_node_position(test_pos)] = nil
                test_pos.x, test_pos.y, test_pos.z = pp.x, pp.y, pp.z + 2
                minetest.set_node(test_pos, { name = LEVER_OFF })
                levers[minetest.hash_node_position(test_pos)] = vector.copy(test_pos)
                pl:set_look_horizontal(0)
                pl:set_look_vertical(0)
                minetest.log("action", "["..MODNAME.."] dev tp: lever moved to "..minetest.pos_to_string(test_pos))
                break
            end
        end
        if txt:find("pull") then
            minetest.load_area(test_pos)
            local node = minetest.get_node(test_pos)
            local def = minetest.registered_nodes[node.name]
            if not (def and def.on_rightclick and (node.name == LEVER_ON or node.name == LEVER_OFF)) then
                minetest.log("warning", "["..MODNAME.."] dev trigger ignored: no lever at "
                    ..minetest.pos_to_string(test_pos).." (found "..node.name..")")
                return
            end
            minetest.log("action", "["..MODNAME.."] dev trigger: pulling selftest lever (was "..node.name..")")
            def.on_rightclick(test_pos, node, fake)
        end
    end)
end


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

minetest.log("action", "["..MODNAME.."] loaded — voxel front-end of P.O.K.E. 💜")
