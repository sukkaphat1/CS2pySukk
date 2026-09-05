// Receiver-local instructions only. Included after the existing skin helpers.
// Schema offsets below are verified against output/client_dll.json.
static const uintptr_t R_STEAMID = 1920, R_PLAYERPAWN = 2324;
static const uintptr_t R_CONTROLLER = 5072, R_OWNER = 1312, R_HEALTH = 844;
static const uintptr_t R_GLOVES = 5776, R_REAPPLY_GLOVES = 5773;

struct RemoteEntry {
    uint64_t player;
    uint32_t slot, pawn, handle;
    uint16_t source, target;
    int kind;
    SkinCfg cfg;
};
struct RemoteOriginal {
    uint16_t def;
    uint64_t id;
    uint32_t high, low, account;
    uint8_t initialized, disallow, restore;
    int paint, seed, stat;
    float wear;
    float attrPaint, attrSeed, attrWear;
    uint64_t mesh;
    uint32_t subclass;
    char model[320];
};
struct RemoteCache {
    int valid, wanted;
    uintptr_t pawn, entity, identity;
    RemoteEntry entry;
    RemoteOriginal original;
    uint64_t lastApply;
    uint64_t lastSeen;
    uintptr_t scene;
    uint32_t hudHandle;
    uintptr_t attachment;
};
static RemoteEntry g_remote[128];
static const int REMOTE_CACHE_CAPACITY = 256;
static RemoteCache g_remoteCache[REMOTE_CACHE_CAPACITY];
static int g_remoteCount = 0;
static uint64_t g_remoteDeadline = 0, g_remoteRules = 0, g_remoteLocal = 0;
static char g_remoteFile[131072], g_remotePath[MAX_PATH];
static uint64_t g_remoteReadTick = 0;
static const char* g_remoteReject = "unknown";
static const char* g_remoteLastReject[128];
static void RemotePlayerString(uint64_t value, char* output) {
    char reversed[21]; int n = 0;
    do { reversed[n++] = (char)('0'+value%10); value /= 10; } while (value);
    int j = 0; while (n) output[j++] = reversed[--n]; output[j] = 0;
}

static int remote_readable(uintptr_t p, SIZE_T n) {
    return p >= 0x10000 && p <= 0x7FFFFFFFFFFFULL - n && !IsBadReadPtr((void*)p, n);
}
static uint64_t remote_now_ms() {
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    uint64_t t = ((uint64_t)ft.dwHighDateTime << 32) | ft.dwLowDateTime;
    return (t - 116444736000000000ULL) / 10000;
}
static int parse_u64(const char** s, const char* end, uint64_t* out) {
    skip_ws(s, end);
    if (*s == end || **s < '0' || **s > '9') return 0;
    uint64_t v = 0;
    while (*s < end && **s >= '0' && **s <= '9') {
        unsigned digit = *(*s)++ - '0';
        if (v > (UINT64_MAX - digit) / 10) return 0;
        v = v * 10 + digit;
    }
    if (*s < end && !is_space(**s)) return 0;
    *out = v;
    return 1;
}
static int RemoteParse(const char* s, const char* end) {
    g_remoteCount = 0;
    char magic[32];
    parse_token(&s, end, magic, sizeof(magic));
    uint64_t deadline, rules, local, count;
    if (!str_eq(magic, "CS2PY_REMOTE_V1") || !parse_u64(&s,end,&deadline) ||
        !parse_u64(&s,end,&rules) || !parse_u64(&s,end,&local) ||
        !parse_u64(&s,end,&count) || count > 128) return 0;
    for (unsigned i = 0; i < count; i++) {
        RemoteEntry* r = &g_remote[i];
        uint64_t v[8], mesh, kind;
        for (int j = 0; j < 8; j++) if (!parse_u64(&s,end,&v[j])) return 0;
        if (!v[0] || v[0] == local || v[1] < 1 || v[1] > 64 ||
            !v[2] || v[2] >= 0xffffffffULL || v[3] > 0xffffffffULL ||
            v[4] > 65535 || v[5] > 65535 || v[6] > 1000000 || v[7] > 1000000) return 0;
        if (!parse_float(&s,end,&r->cfg.wear) || !(r->cfg.wear >= 0 && r->cfg.wear <= 1) ||
            !parse_u64(&s,end,&mesh) || (mesh != 1 && mesh != 2) ||
            !parse_u64(&s,end,&kind) || kind > 1) return 0;
        parse_token(&s,end,r->cfg.model,sizeof(r->cfg.model));
        if (!r->cfg.model[0] || str_contains(r->cfg.model,"..") ||
            !str_contains(r->cfg.model,".vmdl")) return 0;
        r->player = v[0]; r->slot = (uint32_t)v[1]; r->pawn = (uint32_t)v[2];
        r->handle = (uint32_t)v[3]; r->source = (uint16_t)v[4]; r->target = (uint16_t)v[5];
        r->cfg.paint = (int)v[6]; r->cfg.seed = (int)v[7];
        r->cfg.meshMask = (int)mesh; r->kind = (int)kind;
        if (r->kind ? !is_glove_def(r->target) :
            (!r->handle || r->handle == 0xffffffffu || is_glove_def(r->target) ||
             !(r->source == r->target || (is_knife_def(r->source) && is_knife_def(r->target))))) return 0;
        for (unsigned j = 0; j < i; j++)
            if (g_remote[j].slot == r->slot && g_remote[j].kind == r->kind) return 0;
    }
    skip_ws(&s,end);
    if (s != end) return 0;
    g_remoteDeadline = deadline; g_remoteRules = rules; g_remoteLocal = local;
    g_remoteCount = (int)count;
    return 1;
}
static void ReadRemoteConfig() {
    uint64_t tick = GetTickCount64();
    if (tick - g_remoteReadTick < 500) return;
    g_remoteReadTick = tick;
    if (!g_remotePath[0]) {
        char up[MAX_PATH];
        DWORD n = GetEnvironmentVariableA("USERPROFILE",up,MAX_PATH);
        if (!n || n >= MAX_PATH) return;
        build_path(g_remotePath,MAX_PATH,up,"cs2py_remote_skins.txt");
    }
    HANDLE f = CreateFileA(g_remotePath,GENERIC_READ,FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                          0,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,0);
    if (f == INVALID_HANDLE_VALUE) { g_remoteCount = 0; return; }
    DWORD size = GetFileSize(f,0), rd = 0;
    int ok = size > 0 && size < sizeof(g_remoteFile) && ReadFile(f,g_remoteFile,size,&rd,0) && rd == size;
    CloseHandle(f);
    if (!ok || !RemoteParse(g_remoteFile,g_remoteFile+rd)) g_remoteCount = 0;
}

// Re-resolve all identities on EVERY use. Never resolve a peer's raw address.
static int RemoteResolve(uintptr_t client, const RemoteEntry* r, uintptr_t* pawnOut,
                         uintptr_t* entityOut, int activeRequired) {
    g_remoteReject = "gloves_disabled";
    if (r->kind || is_glove_def(r->target)) return 0;
    g_remoteReject = "controller_or_steamid";
    uintptr_t controller = ResolveEntity(client,r->slot);
    if (!remote_readable(controller,R_PLAYERPAWN+4) ||
        *(uint64_t*)(controller+R_STEAMID) != r->player ||
        *(uint32_t*)(controller+R_PLAYERPAWN) != r->pawn) return 0;
    uintptr_t pawn = ResolveEntity(client,r->pawn);
    g_remoteReject = "pawn_identity";
    if (!remote_readable(pawn,OFF_M_HHUDMODELARMS+4) ||
        pawn == *(uintptr_t*)(client+OFF_DW_LOCAL_PLAYER_PAWN) ||
        ResolveEntity(client,*(uint32_t*)(pawn+R_CONTROLLER)) != controller) return 0;
    g_remoteReject = "player_dead";
    if (activeRequired && *(int*)(pawn+R_HEALTH) <= 0) return 0;
    uintptr_t entity = pawn;
    if (!r->kind) {
        uintptr_t ws = *(uintptr_t*)(pawn+OFF_M_PWEAPONSERVICES);
        g_remoteReject = "weapon_services";
        if (!remote_readable(ws,OFF_M_HACTIVEWEAPON+4)) return 0;
        g_remoteReject = "weapon_switch_pending";
        if (activeRequired && *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) != r->handle) return 0;
        entity = ResolveEntity(client,r->handle);
        g_remoteReject = "weapon_owner";
        if (!remote_readable(entity,5820) ||
            *(uint32_t*)(entity+R_OWNER) != r->pawn) return 0;
        if (activeRequired) {
            uintptr_t node = *(uintptr_t*)(entity+OFF_M_PGAMESCENENODE);
            g_remoteReject = "scene_not_ready_or_dormant";
            if (!remote_readable(node,OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK+8) ||
                *(uint8_t*)(node+259)) return 0; // dormant / not transmitted
        }
        uint16_t def = *(uint16_t*)(entity+OFF_M_ATTRIBUTEMANAGER+OFF_M_ITEM+OFF_M_ITEMDEFINDEX);
        g_remoteReject = "weapon_definition";
        if (activeRequired && !(def == r->target || (is_knife_def(def) && is_knife_def(r->target)))) return 0;
        g_remoteReject = "knife_attachment_refresh_unavailable";
        if (activeRequired && is_knife_def(r->target) && (!g_updateSubclass || !g_updateWeaponVm)) return 0;
    }
    *pawnOut = pawn; *entityOut = entity;
    return 1;
}
static uintptr_t RemoteScene(uintptr_t entity) {
    uintptr_t node = *(uintptr_t*)(entity+OFF_M_PGAMESCENENODE);
    return remote_readable(node,OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK+8) ? node : 0;
}
static int RemoteEnsureMesh(uintptr_t entity, uint64_t mesh) {
    // Material rebuilds can replace/reset the scene node. Always reacquire it
    // AFTER a refresh, and repair only the mesh when nothing else changed.
    uintptr_t node = RemoteScene(entity);
    if (!node || !g_setMask) return 0;
    if (*(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == mesh) return 0;
    g_setMask((void*)node,mesh);
    return 1;
}
static uintptr_t RemoteAttachment(uintptr_t client, uintptr_t pawn, uintptr_t weapon) {
    // Use the handle provided by this exact weapon, never search other players.
    uintptr_t attachment = ResolveEntity(client,*(uint32_t*)(weapon+5808)); // m_hViewmodelAttachment
    if (!remote_readable(attachment,R_OWNER+4) || attachment == weapon || attachment == pawn) return 0;
    uintptr_t owner = ResolveEntity(client,*(uint32_t*)(attachment+R_OWNER));
    uintptr_t node = RemoteScene(attachment);
    if (!node) return 0;
    uintptr_t parent = *(uintptr_t*)(node+56);
    if (owner != pawn && owner != weapon && parent != RemoteScene(weapon)) return 0;
    return attachment;
}
static int RemoteVisualMeshes(uintptr_t client, uintptr_t pawn, uintptr_t weapon, int mesh) {
    int repaired = RemoteEnsureMesh(weapon,(uint64_t)mesh);
    uintptr_t attachment = RemoteAttachment(client,pawn,weapon);
    if (attachment) repaired += RemoteEnsureMesh(attachment,(uint64_t)mesh);
    // This is the same child-mesh path that makes the local Printstream UVs
    // correct. RemoteResolve has already checked whose active weapon this is.
    return repaired + ApplyViewmodelMask(client,pawn,mesh,true);
}
static uintptr_t RemoteItem(uintptr_t entity, int kind) {
    return entity + (kind ? R_GLOVES : OFF_M_ATTRIBUTEMANAGER+OFF_M_ITEM);
}
static float RemoteAttr(uintptr_t item, uint16_t def, float fallback) {
    uintptr_t vec = item+520+8;
    int count = *(int*)vec;
    uintptr_t data = *(uintptr_t*)(vec+8);
    if (count < 0 || count > 64 || !remote_readable(data,(SIZE_T)count*72)) return fallback;
    for (int i = 0; i < count; i++)
        if (*(uint16_t*)(data+i*72+48) == def) return *(float*)(data+i*72+52);
    return fallback;
}

// Missing attributes are NOT equivalent to correct fallback fields. Both local
// and shared weapons use this check; -1 cannot be a valid paint/seed/wear.
static int SkinAttributesWrong(uintptr_t entity, const SkinCfg* cfg) {
    uintptr_t item = RemoteItem(entity,0);
    return RemoteAttr(item,6,-1) != (float)cfg->paint ||
        RemoteAttr(item,7,-1) != (float)cfg->seed || RemoteAttr(item,8,-1) != cfg->wear;
}
static void RepairSkinFields(uintptr_t entity, const SkinCfg* cfg, uint16_t def) {
    uintptr_t item = RemoteItem(entity,0);
    if (*(uint16_t*)(item+OFF_M_ITEMDEFINDEX) != def ||
        *(uint64_t*)(item+OFF_M_ITEMID) != 0xffffffff00000000ULL ||
        *(uint32_t*)(item+OFF_M_ITEMIDHIGH) != 0xffffffffu ||
        *(uint8_t*)(item+OFF_M_BINITIALIZED) != 1 ||
        *(uint8_t*)(item+OFF_M_BDISALLOWSOC) != 1 ||
        *(uint8_t*)(item+OFF_M_BRESTORECUSTOM) != 1 ||
        *(int*)(entity+OFF_M_FALLBACKPAINTKIT) != cfg->paint ||
        *(int*)(entity+OFF_M_FALLBACKSEED) != cfg->seed ||
        *(float*)(entity+OFF_M_FALLBACKWEAR) != cfg->wear)
        PokeFields(entity,cfg,def,true);
}
static int KnifePresentationWrong(uintptr_t entity, const SkinCfg* cfg, uint16_t def) {
    if (!is_knife_def(def)) return 0;
    if (*(uint32_t*)(entity+896) != MakeSubclassToken(def)) return 1;
    uintptr_t scene = RemoteScene(entity);
    uintptr_t name = scene ? *(uintptr_t*)(scene+OFF_M_MODELSTATE+168) : 0;
    return remote_readable(name,320) && !str_eq((const char*)name,cfg->model);
}

// Bind cosmetics to an observed physical weapon, not its current holder's
// loadout. No writes are made through these cached pointers: callers must first
// verify the CURRENT pawn/owner and its full (including serial) active handle.
// Thus a dropped gun can be remembered without trusting an index-only resolver
// to write to it on the ground. A recycled slot with a new handle cannot inherit.
struct WeaponBinding {
    int valid;
    uint32_t handle;
    uintptr_t entity, identity;
    uint64_t ownerXuid, donor;
    uint16_t target;
    SkinCfg cfg;
};
static WeaponBinding g_bindings[256];
static uintptr_t g_bindingRules = 0, g_bindingList = 0;
static void BindingSession(uintptr_t client) {
    uintptr_t rules = *(uintptr_t*)(client+OFF_DW_GAMERULES);
    uintptr_t list = *(uintptr_t*)(client+OFF_DW_ENTITY_LIST);
    if (!rules || rules != g_bindingRules || list != g_bindingList) {
        memset(g_bindings,0,sizeof(g_bindings));
        g_bindingRules = rules; g_bindingList = list;
    }
}
static int BindingAlive(uintptr_t client, WeaponBinding* b) {
    if (!b->valid) return 0;
    uintptr_t entity = ResolveEntity(client,b->handle);
    if (entity != b->entity || !remote_readable(entity,5820) ||
        *(uintptr_t*)(entity+16) != b->identity || // CEntityInstance::m_pEntity
        *(uint64_t*)(entity+OFF_M_OWNERXUIDLOW) != b->ownerXuid) {
        b->valid = 0; return 0;
    }
    return 1;
}
static WeaponBinding* FindWeaponBinding(uintptr_t client, uint32_t handle, uintptr_t entity) {
    BindingSession(client);
    for (int i = 0; i < 256; i++) {
        WeaponBinding* b = &g_bindings[i];
        if (!b->valid) continue;
        // An observed serial change is definitive even if the allocator reused
        // both the entity and its identity address between our samples.
        if ((b->handle & 0x7fff) == (handle & 0x7fff) && b->handle != handle) b->valid = 0;
        if (b->handle == handle && BindingAlive(client,b) && b->entity == entity) return b;
    }
    return 0;
}
static void RememberWeaponSkin(uintptr_t client, uint32_t handle, uintptr_t entity,
                               uint64_t player, uint16_t target, const SkinCfg* cfg) {
    WeaponBinding* b = FindWeaponBinding(client,handle,entity);
    if (b && b->donor != player) return; // pickup never overwrites the donor selection
    if (!b) {
        for (int i = 0; i < 256; i++)
            if (!BindingAlive(client,&g_bindings[i])) { b = &g_bindings[i]; break; }
    }
    if (!b) return; // bounded cache; never evict another live weapon
    b->valid = 1; b->handle = handle; b->entity = entity;
    b->identity = *(uintptr_t*)(entity+16);
    b->ownerXuid = *(uint64_t*)(entity+OFF_M_OWNERXUIDLOW);
    b->donor = player; b->target = target; b->cfg = *cfg;
}
static void RemoteCapture(RemoteCache* c) {
    uintptr_t item = RemoteItem(c->entity,c->entry.kind);
    RemoteOriginal* o = &c->original;
    o->def = *(uint16_t*)(item+OFF_M_ITEMDEFINDEX);
    o->id = *(uint64_t*)(item+OFF_M_ITEMID);
    o->high = *(uint32_t*)(item+OFF_M_ITEMIDHIGH); o->low = *(uint32_t*)(item+OFF_M_ITEMIDLOW);
    o->account = *(uint32_t*)(item+OFF_M_ACCOUNTID);
    o->initialized = *(uint8_t*)(item+OFF_M_BINITIALIZED);
    o->disallow = *(uint8_t*)(item+OFF_M_BDISALLOWSOC);
    o->restore = *(uint8_t*)(item+OFF_M_BRESTORECUSTOM);
    o->paint = c->entry.kind ? 0 : *(int*)(c->entity+OFF_M_FALLBACKPAINTKIT);
    o->seed = c->entry.kind ? 0 : *(int*)(c->entity+OFF_M_FALLBACKSEED);
    o->wear = c->entry.kind ? 0 : *(float*)(c->entity+OFF_M_FALLBACKWEAR);
    o->stat = c->entry.kind ? -1 : *(int*)(c->entity+OFF_M_FALLBACKSTATTRAK);
    o->attrPaint = RemoteAttr(item,6,(float)o->paint);
    o->attrSeed = RemoteAttr(item,7,(float)o->seed);
    o->attrWear = RemoteAttr(item,8,o->wear);
    o->model[0] = 0; o->mesh = 1;
    if (!c->entry.kind) {
        o->subclass = *(uint32_t*)(c->entity+896);
        uintptr_t node = *(uintptr_t*)(c->entity+OFF_M_PGAMESCENENODE);
        if (remote_readable(node,OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK+8)) {
            o->mesh = *(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK);
            uintptr_t name = *(uintptr_t*)(node+OFF_M_MODELSTATE+168);
            if (remote_readable(name,320)) copy_str(o->model,(const char*)name,320);
        }
    }
}
static void RemoteRefresh(uintptr_t entity, uintptr_t item, const SkinCfg* cfg, int kind) {
    if (kind) return;
    // One material implementation for local and shared weapons. This includes
    // the same attribute order and the same composite-material calls.
    RefreshWeaponMaterials(entity,cfg);
}
static void RemoteRestore(uintptr_t client, RemoteCache* c) {
    uintptr_t pawn, entity;
    if (c->valid && RemoteResolve(client,&c->entry,&pawn,&entity,0) &&
        pawn == c->pawn && entity == c->entity && *(uintptr_t*)(entity+16) == c->identity && g_setAttr) {
        uintptr_t item = RemoteItem(entity,c->entry.kind);
        RemoteOriginal* o = &c->original;
        *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = o->def;
        *(uint64_t*)(item+OFF_M_ITEMID) = o->id;
        *(uint32_t*)(item+OFF_M_ITEMIDHIGH) = o->high; *(uint32_t*)(item+OFF_M_ITEMIDLOW) = o->low;
        *(uint32_t*)(item+OFF_M_ACCOUNTID) = o->account;
        *(uint8_t*)(item+OFF_M_BINITIALIZED) = o->initialized;
        *(uint8_t*)(item+OFF_M_BDISALLOWSOC) = o->disallow;
        *(uint8_t*)(item+OFF_M_BRESTORECUSTOM) = o->restore;
        SkinCfg original = {}; original.paint = (int)o->attrPaint;
        original.seed = (int)o->attrSeed; original.wear = o->attrWear;
        if (!c->entry.kind) {
            *(int*)(entity+OFF_M_FALLBACKPAINTKIT) = o->paint;
            *(int*)(entity+OFF_M_FALLBACKSEED) = o->seed;
            *(float*)(entity+OFF_M_FALLBACKWEAR) = o->wear;
            *(int*)(entity+OFF_M_FALLBACKSTATTRAK) = o->stat;
            if (is_knife_def(c->entry.target) && o->model[0] && g_setModel) {
                g_setModel((void*)entity,o->model);
                *(uint32_t*)(entity+896) = o->subclass;
                if (g_updateSubclass) g_updateSubclass((void*)entity);
            }
        }
        RemoteRefresh(entity,item,&original,c->entry.kind);
        if (!c->entry.kind) RemoteEnsureMesh(entity,o->mesh);
    }
    c->valid = 0;
}
static int RemoteSame(const RemoteEntry* a, const RemoteEntry* b) {
    return a->player == b->player && a->slot == b->slot && a->pawn == b->pawn && a->handle == b->handle &&
        a->kind == b->kind && a->target == b->target && a->cfg.paint == b->cfg.paint &&
        a->cfg.seed == b->cfg.seed && a->cfg.wear == b->cfg.wear &&
        a->cfg.meshMask == b->cfg.meshMask && str_eq(a->cfg.model,b->cfg.model);
}
static RemoteCache* RemoteCacheFor(const RemoteEntry* r) {
    RemoteCache* freeSlot = 0;
    for (int i = 0; i < REMOTE_CACHE_CAPACITY; i++) {
        RemoteCache* c = &g_remoteCache[i];
        if (c->valid && c->entry.player == r->player && c->entry.pawn == r->pawn &&
            c->entry.handle == r->handle && c->entry.kind == r->kind) return c;
        if (!c->valid && !freeSlot) freeSlot = c;
    }
    return freeSlot;
}
struct LocalSkinState {
    int valid;
    uintptr_t pawn, entity, identity, scene, attachment, rules;
    uint32_t handle, pawnHandle, hudHandle;
    uint16_t target;
    SkinCfg cfg;
    uint64_t lastApply, settleAt;
};
static LocalSkinState g_localSkin;

static void ApplyLocalSkins(uintptr_t client) {
    BindingSession(client);
    uintptr_t rules = *(uintptr_t*)(client+OFF_DW_GAMERULES);
    uintptr_t pawn = *(uintptr_t*)(client+OFF_DW_LOCAL_PLAYER_PAWN);
    if (!rules || !remote_readable(pawn,OFF_M_HHUDMODELARMS+4) || *(int*)(pawn+R_HEALTH) <= 0) {
        g_localSkin.valid = 0; return;
    }
    uintptr_t controller = ResolveEntity(client,*(uint32_t*)(pawn+R_CONTROLLER));
    if (!remote_readable(controller,R_PLAYERPAWN+4)) { g_localSkin.valid = 0; return; }
    uint64_t player = *(uint64_t*)(controller+R_STEAMID);
    uint32_t pawnHandle = *(uint32_t*)(controller+R_PLAYERPAWN);
    uintptr_t ws = *(uintptr_t*)(pawn+OFF_M_PWEAPONSERVICES);
    if (!player || ResolveEntity(client,pawnHandle) != pawn || !remote_readable(ws,OFF_M_HACTIVEWEAPON+4)) {
        g_localSkin.valid = 0; return;
    }
    uint32_t handle = *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON);
    uintptr_t entity = ResolveEntity(client,handle);
    if (!remote_readable(entity,5820) || *(uint32_t*)(entity+R_OWNER) != pawnHandle) {
        g_localSkin.valid = 0; return;
    }
    uintptr_t scene = RemoteScene(entity);
    if (!scene || *(uint8_t*)(scene+259)) { g_localSkin.valid = 0; return; }
    uint16_t def = *(uint16_t*)(RemoteItem(entity,0)+OFF_M_ITEMDEFINDEX);
    SkinCfg selected = {}; uint16_t target = 0;
    AcquireSRWLockShared(&g_lock);
    for (int i = 0; i < g_skin_count; i++) {
        if ((is_knife_def(def) && is_knife_def(g_skins[i].def)) || g_skins[i].def == def) {
            selected = g_skins[i].cfg; target = g_skins[i].def;
            if (!is_knife_def(def)) break;
        }
    }
    ReleaseSRWLockShared(&g_lock);
    WeaponBinding* binding = FindWeaponBinding(client,handle,entity);
    int inherited = binding && binding->donor != player &&
        (binding->target == def || (is_knife_def(binding->target) && is_knife_def(def)));
    if (inherited) { selected = binding->cfg; target = binding->target; }
    if (!target || is_glove_def(target) || !g_setAttr || !g_updateSkin || !g_setMask ||
        (is_knife_def(target) && (!g_setModel || !g_updateSubclass || !g_updateWeaponVm))) {
        g_localSkin.valid = 0; return;
    }
    const SkinCfg* cfg = &selected;
    LocalSkinState* c = &g_localSkin;
    uint32_t hudHandle = *(uint32_t*)(pawn+OFF_M_HHUDMODELARMS);
    uintptr_t attachment = RemoteAttachment(client,pawn,entity);
    int respawn = !c->valid || c->rules != rules || c->pawn != pawn || c->pawnHandle != pawnHandle;
    int selection = respawn || c->entity != entity || c->identity != *(uintptr_t*)(entity+16) ||
        c->handle != handle || c->target != target ||
        c->cfg.paint != cfg->paint || c->cfg.seed != cfg->seed || c->cfg.wear != cfg->wear ||
        c->cfg.meshMask != cfg->meshMask || !str_eq(c->cfg.model,cfg->model);
    int recreated = c->scene != scene || c->hudHandle != hudHandle || c->attachment != attachment;
    uint64_t tick = GetTickCount64();
    RepairSkinFields(entity,cfg,target);
    int wrong = SkinAttributesWrong(entity,cfg) || KnifePresentationWrong(entity,cfg,target);
    int settling = c->settleAt && tick >= c->settleAt;
    if (selection || recreated || ((wrong || settling) && tick-c->lastApply >= 750)) {
        PokeFields(entity,cfg,target,true); // preserve the real original-owner XUID
        RefreshWeaponMaterials(entity,cfg);
        ApplyKnifePresentation(client,pawn,entity,cfg,target);
        c->lastApply = tick;
        // One delayed rebuild after a new pawn, not a recurring refresh timer.
        // This lets late spawn initialization finish before committing materials.
        if (respawn) c->settleAt = tick+750;
        else if (settling) c->settleAt = 0;
        DllLog("local apply: def=%u paint=%d seed=%d inherited=%d reason=%s",
            (unsigned)target,cfg->paint,cfg->seed,inherited,
            respawn ? "pawn_ready" : selection ? "selection" : recreated ? "scene_replaced" : settling ? "spawn_settle" : "state_reset");
    }
    RemoteVisualMeshes(client,pawn,entity,cfg->meshMask);
    c->valid = 1; c->rules = rules; c->pawn = pawn; c->pawnHandle = pawnHandle;
    c->entity = entity; c->handle = handle; c->target = target; c->cfg = *cfg;
    c->identity = *(uintptr_t*)(entity+16);
    c->scene = RemoteScene(entity); c->hudHandle = hudHandle;
    c->attachment = RemoteAttachment(client,pawn,entity);
    RememberWeaponSkin(client,handle,entity,player,target,cfg);
}

static void ApplyRemoteSkins(uintptr_t client) {
    ReadRemoteConfig();
    uint64_t now = remote_now_ms();
    int count = g_remoteCount;
    int sessionValid = 1;
    if (now > g_remoteDeadline || g_remoteDeadline > now+10000 ||
        *(uintptr_t*)(client+OFF_DW_GAMERULES) != g_remoteRules) sessionValid = 0;
    // Verify the file belongs to this local player and this live session.
    uintptr_t localPawn = *(uintptr_t*)(client+OFF_DW_LOCAL_PLAYER_PAWN);
    uintptr_t localController = remote_readable(localPawn,R_CONTROLLER+4) ?
        ResolveEntity(client,*(uint32_t*)(localPawn+R_CONTROLLER)) : 0;
    if (!remote_readable(localController,R_STEAMID+8) ||
        *(uint64_t*)(localController+R_STEAMID) != g_remoteLocal) sessionValid = 0;
    if (!g_setAttr || !g_updateSkin || !g_setModel || !g_setMask) sessionValid = 0;
    if (!sessionValid) count = 0;
    for (int i = 0; i < REMOTE_CACHE_CAPACITY; i++) g_remoteCache[i].wanted = 0;
    int budget = 4;
    for (int i = 0; i < count; i++) {
        RemoteEntry effective = g_remote[i];
        RemoteEntry* r = &effective;
        if (r->kind || is_glove_def(r->target)) continue;
        RemoteCache* c = RemoteCacheFor(r);
        if (!c) continue;
        int cacheIndex = (r->slot-1)*2+r->kind;
        uint64_t tick = GetTickCount64();
        // A current instruction can temporarily fail the active/dormancy
        // checks. Keep the baseline, without writing through a failed check.
        if (c->valid) { c->wanted = 1; c->lastSeen = tick; }
        uintptr_t pawn, entity;
        if (!RemoteResolve(client,r,&pawn,&entity,1)) {
            if (!g_remoteLastReject[cacheIndex] || !str_eq(g_remoteLastReject[cacheIndex],g_remoteReject)) {
                char playerText[21]; RemotePlayerString(r->player,playerText);
                DllLog("remote skipped: player=%s def=%u paint=%d reason=%s",playerText,(unsigned)r->target,r->cfg.paint,g_remoteReject);
                g_remoteLastReject[cacheIndex] = g_remoteReject;
            }
            continue;
        }
        g_remoteLastReject[cacheIndex] = 0;
        WeaponBinding* binding = FindWeaponBinding(client,r->handle,entity);
        if (binding && binding->donor != r->player &&
            (binding->target == r->target || (is_knife_def(binding->target) && is_knife_def(r->target)))) {
            r->target = binding->target; r->cfg = binding->cfg;
        }
        c->wanted = 1;
        c->lastSeen = tick;
        uintptr_t item = RemoteItem(entity,r->kind);
        uintptr_t scene = r->kind ? 0 : RemoteScene(entity);
        int selectionChanged = !c->valid || c->pawn != pawn || c->entity != entity ||
            c->identity != *(uintptr_t*)(entity+16) || !RemoteSame(&c->entry,r);
        uint32_t hudHandle = *(uint32_t*)(pawn+OFF_M_HHUDMODELARMS);
        uintptr_t attachment = RemoteAttachment(client,pawn,entity);
        int recreated = c->valid && (c->scene != scene || c->hudHandle != hudHandle || c->attachment != attachment);
        int changed = selectionChanged || recreated;
        if (!changed) {
            RepairSkinFields(entity,&r->cfg,r->target);
        }
        // Inspect every pass, but rate-limit expensive repairs independently.
        int attributesWrong = SkinAttributesWrong(entity,&r->cfg);
        int presentationWrong = KnifePresentationWrong(entity,&r->cfg,r->target);
        if (!changed && tick-c->lastApply >= 750) {
            changed = attributesWrong || presentationWrong;
        }
        if (!changed) {
            RememberWeaponSkin(client,r->handle,entity,r->player,r->target,&r->cfg);
            if (budget > 0 && RemoteVisualMeshes(client,pawn,entity,r->cfg.meshMask)) {
                budget--;
            }
            continue;
        }
        if (budget <= 0) continue;
        budget--;
        if (c->valid && (c->pawn != pawn || c->entity != entity || c->identity != *(uintptr_t*)(entity+16) ||
            c->entry.player != r->player || c->entry.pawn != r->pawn || c->entry.handle != r->handle))
            RemoteRestore(client,c);
        if (!c->valid) {
            c->pawn = pawn; c->entity = entity; c->entry = *r;
            c->identity = *(uintptr_t*)(entity+16);
            RemoteCapture(c);
        }
        c->entry = *r;
        PokeFields(entity,&r->cfg,r->target,true);
        RemoteRefresh(entity,item,&r->cfg,r->kind);
        // Preserve the working local ordering: materials first, then knife
        // model + HUD model + subclass + attachment/viewmodel refresh.
        if (is_knife_def(r->target) && (selectionChanged || recreated || presentationWrong))
            ApplyKnifePresentation(client,pawn,entity,&r->cfg,r->target);
        RemoteVisualMeshes(client,pawn,entity,r->cfg.meshMask);
        c->valid = 1;
        c->scene = r->kind ? 0 : RemoteScene(entity);
        c->hudHandle = hudHandle;
        c->attachment = RemoteAttachment(client,pawn,entity);
        c->lastApply = tick;
        RememberWeaponSkin(client,r->handle,entity,r->player,r->target,&r->cfg);
        char playerText[21]; RemotePlayerString(r->player,playerText);
        DllLog("remote apply: player=%s slot=%u def=%u paint=%d mesh=%d reason=%s entity=%p",
            playerText,r->slot,(unsigned)r->target,r->cfg.paint,r->cfg.meshMask,
            selectionChanged ? "selection" : recreated ? "scene_replaced" : "attributes_reset",(void*)entity);
    }
    for (int i = 0; i < REMOTE_CACHE_CAPACITY && budget > 0; i++) {
        if (g_remoteCache[i].valid && !g_remoteCache[i].wanted) {
            RemoteCache* old = &g_remoteCache[i];
            // Keep each owned weapon's baseline while its player holds a
            // different shared weapon. Switching back must not undo/reapply it.
            if (sessionValid) {
                int playerPresent = 0;
                for (int j = 0; j < count; j++)
                    if (!g_remote[j].kind && g_remote[j].player == old->entry.player && g_remote[j].pawn == old->entry.pawn)
                        playerPresent = 1;
                uintptr_t pawn, entity;
                if (playerPresent && RemoteResolve(client,&old->entry,&pawn,&entity,0) &&
                    pawn == old->pawn && entity == old->entity) {
                    uintptr_t ws = *(uintptr_t*)(pawn+OFF_M_PWEAPONSERVICES);
                    if (remote_readable(ws,OFF_M_HACTIVEWEAPON+4) &&
                        *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) != old->entry.handle) continue;
                }
            }
            // Sampling/render visibility can briefly disappear while switching.
            // Expired files/sessions still restore immediately.
            if (sessionValid && GetTickCount64()-g_remoteCache[i].lastSeen < 1500) continue;
            RemoteRestore(client,&g_remoteCache[i]); budget--;
        }
    }
}
