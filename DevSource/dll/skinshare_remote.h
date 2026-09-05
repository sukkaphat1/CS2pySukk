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
    uintptr_t pawn, entity;
    RemoteEntry entry;
    RemoteOriginal original;
    uint64_t lastApply;
    uint64_t lastSeen, nextSettle;
    int settleRemaining;
    uintptr_t scene;
};
static RemoteEntry g_remote[128];
static RemoteCache g_remoteCache[128];
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
    g_remoteReject = "controller_or_steamid";
    uintptr_t controller = ResolveEntity(client,r->slot);
    if (!remote_readable(controller,R_PLAYERPAWN+4) ||
        *(uint64_t*)(controller+R_STEAMID) != r->player ||
        *(uint32_t*)(controller+R_PLAYERPAWN) != r->pawn) return 0;
    uintptr_t pawn = ResolveEntity(client,r->pawn);
    g_remoteReject = "pawn_identity";
    if (!remote_readable(pawn,R_GLOVES+1200) ||
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
        if (!remote_readable(entity,OFF_M_FALLBACKSTATTRAK+4) ||
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
    g_setAttr((void*)item,"set item texture prefab",(float)cfg->paint);
    g_setAttr((void*)item,"set item texture seed",(float)cfg->seed);
    g_setAttr((void*)item,"set item texture wear",cfg->wear);
    if (kind) {
        // Glove item view belongs to the pawn. Ask the game to replace its
        // glove visuals; never SetModel on the pawn or create a second wearable.
        *(uint8_t*)(entity+R_REAPPLY_GLOVES) = 1;
    } else {
        if (g_updateSkin) g_updateSkin((void*)entity,true);
        if (g_updateComp) g_updateComp((void*)(entity+0x608),true);
        if (g_updateCompSet) g_updateCompSet((void*)entity,false);
    }
}
static void RemoteRestore(uintptr_t client, RemoteCache* c) {
    uintptr_t pawn, entity;
    if (c->valid && RemoteResolve(client,&c->entry,&pawn,&entity,0) &&
        pawn == c->pawn && entity == c->entity && g_setAttr) {
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
    return a->player == b->player && a->pawn == b->pawn && a->handle == b->handle &&
        a->kind == b->kind && a->target == b->target && a->cfg.paint == b->cfg.paint &&
        a->cfg.seed == b->cfg.seed && a->cfg.wear == b->cfg.wear &&
        a->cfg.meshMask == b->cfg.meshMask && str_eq(a->cfg.model,b->cfg.model);
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
    for (int i = 0; i < 128; i++) g_remoteCache[i].wanted = 0;
    int budget = 4;
    for (int i = 0; i < count; i++) {
        RemoteEntry* r = &g_remote[i];
        RemoteCache* c = &g_remoteCache[(r->slot-1)*2+r->kind];
        int cacheIndex = (r->slot-1)*2+r->kind;
        uint64_t tick = GetTickCount64();
        // A current instruction can temporarily fail the active/dormancy
        // checks. Keep the baseline, without writing through a failed check.
        if (c->valid && RemoteSame(&c->entry,r)) { c->wanted = 1; c->lastSeen = tick; }
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
        c->wanted = 1;
        c->lastSeen = tick;
        uintptr_t item = RemoteItem(entity,r->kind);
        uintptr_t scene = r->kind ? 0 : RemoteScene(entity);
        int selectionChanged = !c->valid || c->pawn != pawn || c->entity != entity || !RemoteSame(&c->entry,r);
        int recreated = c->valid && !r->kind && c->scene != scene;
        int changed = selectionChanged || recreated;
        int settling = !changed && c->settleRemaining > 0 && tick >= c->nextSettle;
        if (!changed && tick-c->lastApply >= 2000) {
            changed = *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) != r->target ||
                *(uint32_t*)(item+OFF_M_ITEMIDHIGH) != 0xffffffffu ||
                *(uint8_t*)(item+OFF_M_BINITIALIZED) != 1;
            if (!r->kind) changed = changed || *(int*)(entity+OFF_M_FALLBACKPAINTKIT) != r->cfg.paint ||
                *(int*)(entity+OFF_M_FALLBACKSEED) != r->cfg.seed ||
                *(float*)(entity+OFF_M_FALLBACKWEAR) != r->cfg.wear ||
                RemoteAttr(item,6,(float)r->cfg.paint) != (float)r->cfg.paint ||
                RemoteAttr(item,7,(float)r->cfg.seed) != (float)r->cfg.seed ||
                RemoteAttr(item,8,r->cfg.wear) != r->cfg.wear;
        }
        if (!changed && !settling) {
            if (!r->kind && budget > 0 && RemoteEnsureMesh(entity,(uint64_t)r->cfg.meshMask)) {
                budget--;
                DllLog("remote mesh repaired: slot=%u def=%u paint=%d mesh=%d",r->slot,(unsigned)r->target,r->cfg.paint,r->cfg.meshMask);
            }
            continue;
        }
        if (budget <= 0) continue;
        budget--;
        if (c->valid && (c->pawn != pawn || c->entity != entity ||
            c->entry.player != r->player || c->entry.pawn != r->pawn || c->entry.handle != r->handle))
            RemoteRestore(client,c);
        if (!c->valid) {
            c->pawn = pawn; c->entity = entity; c->entry = *r;
            RemoteCapture(c);
        }
        c->entry = *r;
        *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = r->target;
        *(uint32_t*)(item+OFF_M_ACCOUNTID) = (uint32_t)r->player;
        *(uint64_t*)(item+OFF_M_ITEMID) = 0xffffffff00000000ULL;
        *(uint32_t*)(item+OFF_M_ITEMIDHIGH) = 0xffffffffu;
        *(uint32_t*)(item+OFF_M_ITEMIDLOW) = 0;
        *(uint8_t*)(item+OFF_M_BINITIALIZED) = 1;
        *(uint8_t*)(item+OFF_M_BDISALLOWSOC) = 1;
        *(uint8_t*)(item+OFF_M_BRESTORECUSTOM) = 1;
        if (!r->kind) {
            *(int*)(entity+OFF_M_FALLBACKPAINTKIT) = r->cfg.paint;
            *(int*)(entity+OFF_M_FALLBACKSEED) = r->cfg.seed;
            *(float*)(entity+OFF_M_FALLBACKWEAR) = r->cfg.wear;
            // Preserve actual ownership/XUID fields. They are not cosmetic IDs.
            if (is_knife_def(r->target) && (selectionChanged || recreated ||
                *(uint32_t*)(entity+896) != MakeSubclassToken(r->target))) {
                g_setModel((void*)entity,r->cfg.model);
                *(uint32_t*)(entity+896) = MakeSubclassToken(r->target);
                if (g_updateSubclass) g_updateSubclass((void*)entity);
            }
        }
        RemoteRefresh(entity,item,&r->cfg,r->kind);
        if (!r->kind) RemoteEnsureMesh(entity,(uint64_t)r->cfg.meshMask);
        c->valid = 1;
        c->scene = r->kind ? 0 : RemoteScene(entity);
        c->lastApply = tick;
        if (selectionChanged || recreated) c->settleRemaining = r->kind ? 0 : 2;
        else if (settling) c->settleRemaining--;
        c->nextSettle = tick+500;
        char playerText[21]; RemotePlayerString(r->player,playerText);
        DllLog("remote apply: player=%s slot=%u kind=%d def=%u paint=%d mesh=%d settle=%d entity=%p",
            playerText,r->slot,r->kind,(unsigned)r->target,r->cfg.paint,r->cfg.meshMask,settling,(void*)entity);
    }
    for (int i = 0; i < 128 && budget > 0; i++) {
        if (g_remoteCache[i].valid && !g_remoteCache[i].wanted) {
            // Sampling/render visibility can briefly disappear while switching.
            // Expired files/sessions still restore immediately.
            if (sessionValid && GetTickCount64()-g_remoteCache[i].lastSeen < 1500) continue;
            RemoteRestore(client,&g_remoteCache[i]); budget--;
        }
    }
}
