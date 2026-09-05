// Isolated fake-memory fixtures. Never opens or writes to a game process.
// Build CRT-free with /ENTRY:RemoteTestMain and kernel32.lib.
#include "skinchanger.cpp"

static int attrCalls = 0, updateCalls = 0, modelCalls = 0, vmCalls = 0;
static uintptr_t vmWeapon = 0;
static uintptr_t Allocate(SIZE_T size);
static void __fastcall FakeWeaponVm(void* entity) { vmCalls++; vmWeapon = (uintptr_t)entity; }
static void __fastcall FakeSubclass(void*) {}
static void __fastcall FakeAttr(void* view,const char* name,float value) {
    attrCalls++;
    uintptr_t item = (uintptr_t)view, vec = item+528;
    uintptr_t data = *(uintptr_t*)(vec+8);
    if (!data) { data = Allocate(4096); *(uintptr_t*)(vec+8) = data; }
    int index = str_contains(name,"prefab") ? 0 : str_contains(name,"seed") ? 1 : 2;
    *(int*)vec = 3;
    *(uint16_t*)(data+index*72+48) = (uint16_t)(index+6);
    *(float*)(data+index*72+52) = value;
}
static void __fastcall FakeUpdate(void* entity,bool) {
    updateCalls++;
    // Reproduce a material refresh resetting the visible mesh.
    uintptr_t node = *(uintptr_t*)((uintptr_t)entity+OFF_M_PGAMESCENENODE);
    if (node) {
        *(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) = 0;
        *(int*)(node+1000) = 1; // fixture-only rendered-material readiness
    }
}
static void __fastcall FakeModel(void* entity,const char* model) {
    modelCalls++;
    uintptr_t node = *(uintptr_t*)((uintptr_t)entity+OFF_M_PGAMESCENENODE);
    uintptr_t name = Allocate(4096);
    copy_str((char*)name,model,320);
    if (node) {
        *(uintptr_t*)(node+OFF_M_MODELSTATE+168) = name;
        // Model initialization can invalidate materials without losing attrs.
        *(int*)(node+1000) = 0;
    }
}
static void __fastcall FakeMask(void* node,uint64_t mesh) {
    *(uint64_t*)((uintptr_t)node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) = mesh;
}
static uintptr_t Allocate(SIZE_T size) {
    uintptr_t result = (uintptr_t)VirtualAlloc(0,size,MEM_COMMIT | MEM_RESERVE,PAGE_READWRITE);
    if (!result) ExitProcess(99);
    return result;
}
static void Check(int value, unsigned code) { if (!value) ExitProcess(code); }

extern "C" void RemoteTestMain() {
    // Fixtures must not append simulated applies to the user's real game log.
    copy_str(g_configPath,"fixture-only",MAX_PATH);
    copy_str(g_logPath,"NUL",MAX_PATH);
    uintptr_t client = Allocate(40*1024*1024), list = Allocate(4096), chunk = Allocate(512*0x70);
    uintptr_t local = Allocate(12000), localController = Allocate(4000);
    uintptr_t pawn = Allocate(12000), controller = Allocate(4000);
    uintptr_t weapon = Allocate(12000), ws = Allocate(4096), node = Allocate(4096);
    *(uintptr_t*)(client+OFF_DW_ENTITY_LIST) = list;
    *(uintptr_t*)(list+0x10) = chunk;
    *(uintptr_t*)(chunk+0x70*1) = localController;
    *(uintptr_t*)(chunk+0x70*64) = controller;
    *(uintptr_t*)(chunk+0x70*100) = pawn;
    *(uintptr_t*)(chunk+0x70*200) = weapon;
    *(uintptr_t*)(client+OFF_DW_GAMERULES) = 123456;
    *(uintptr_t*)(client+OFF_DW_LOCAL_PLAYER_PAWN) = local;
    // Production lifetime guard runs against fixture-owned engine memory too.
    g_liveEngine = Allocate(10*1024*1024);
    uintptr_t network = Allocate(4096);
    *(uintptr_t*)(g_liveEngine+OFF_ENGINE_NETWORK) = network;
    *(int*)(network+OFF_ENGINE_SIGNON) = 6;
    g_control.pid = GetCurrentProcessId();
    g_control.deadline = remote_now_ms()+5000;
    g_control.rules = 123456; g_control.list = list;
    g_localEnabled = g_shareEnabled = 1;
    *(uint32_t*)(local+R_CONTROLLER) = 1;
    *(uint64_t*)(localController+R_STEAMID) = 76561198864001604ULL;
    *(uint64_t*)(controller+R_STEAMID) = 76561198000000002ULL;
    *(uint32_t*)(controller+R_PLAYERPAWN) = 0x8064;
    *(uint32_t*)(pawn+R_CONTROLLER) = 64;
    *(int*)(pawn+R_HEALTH) = 100;
    *(uintptr_t*)(pawn+OFF_M_PWEAPONSERVICES) = ws;
    *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) = 0x80c8;
    *(uint32_t*)(weapon+R_OWNER) = 0x8064;
    *(uintptr_t*)(weapon+OFF_M_PGAMESCENENODE) = node;
    uintptr_t item = RemoteItem(weapon,0);
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 9;
    *(int*)(weapon+OFF_M_FALLBACKPAINTKIT) = 51;
    *(uint32_t*)(weapon+OFF_M_OWNERXUIDLOW) = 123;
    *(uint32_t*)(weapon+OFF_M_OWNERXUIDHIGH) = 456;
    g_setAttr = FakeAttr; g_updateSkin = FakeUpdate; g_setModel = FakeModel; g_setMask = FakeMask;
    g_updateWeaponVm = FakeWeaponVm;
    g_updateSubclass = FakeSubclass;
    g_remoteReadTick = GetTickCount64()+100000; // refresh immediately before each call below
    const char valid[] = "CS2PY_REMOTE_V1 1000 123456 76561198864001604 1\n76561198000000002 64 32868 32968 9 9 756 7 0.125 2 0 weapons/models/awp/weapon_snip_awp.vmdl\n";
    Check(RemoteParse(valid,valid+sizeof(valid)-1),1);
    RemoteEntry saved = g_remote[0];
    uintptr_t p, e;
    Check(RemoteResolve(client,&saved,&p,&e,1) && p == pawn && e == weapon,2);
    RemoteEntry bad = saved; bad.player++;
    Check(!RemoteResolve(client,&bad,&p,&e,1),3);
    bad = saved; bad.pawn += 0x8000;
    Check(!RemoteResolve(client,&bad,&p,&e,1),4);
    bad = saved; bad.handle += 0x8000;
    Check(!RemoteResolve(client,&bad,&p,&e,1),5);
    *(uint32_t*)(weapon+R_OWNER) = 1;
    Check(!RemoteResolve(client,&saved,&p,&e,1),6);
    *(uint32_t*)(weapon+R_OWNER) = 0x8064;
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 4;
    Check(!RemoteResolve(client,&saved,&p,&e,1),7);
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 9;
    *(int*)(pawn+R_HEALTH) = 0;
    Check(!RemoteResolve(client,&saved,&p,&e,1),8);
    *(int*)(pawn+R_HEALTH) = 100;
    g_remoteDeadline = remote_now_ms()+3000;
    g_remoteReadTick = GetTickCount64();
    ApplyRemoteSkins(client);
    Check(attrCalls == 3 && updateCalls == 1,9);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 756,10);
    Check(*(uint32_t*)(weapon+OFF_M_OWNERXUIDLOW) == 123 && *(uint32_t*)(weapon+OFF_M_OWNERXUIDHIGH) == 456,11);
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(attrCalls == 3 && updateCalls == 1,12); // unchanged: no expensive calls
    Check(*(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2,19);
    // The visible attachment and the matched pawn's HUD child receive the
    // same legacy mesh as the local renderer, not just the network entity.
    uintptr_t attached = Allocate(12000), attachedNode = Allocate(4096);
    uintptr_t arms = Allocate(12000), armsNode = Allocate(4096), hudChild = Allocate(4096);
    *(uintptr_t*)(chunk+0x70*300) = attached;
    *(uintptr_t*)(chunk+0x70*301) = arms;
    *(uint32_t*)(weapon+5808) = 300;
    *(uint32_t*)(attached+R_OWNER) = 0x8064;
    *(uintptr_t*)(attached+OFF_M_PGAMESCENENODE) = attachedNode;
    *(uint32_t*)(pawn+OFF_M_HHUDMODELARMS) = 301;
    *(uintptr_t*)(arms+OFF_M_PGAMESCENENODE) = armsNode;
    *(uintptr_t*)(armsNode+64) = hudChild;
    RemoteVisualMeshes(client,pawn,weapon,2);
    Check(*(uint64_t*)(attachedNode+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2 &&
          *(uint64_t*)(hudChild+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2,30);
    *(uint32_t*)(attached+R_OWNER) = 1;
    *(uint64_t*)(attachedNode+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) = 0;
    RemoteVisualMeshes(client,pawn,weapon,2);
    Check(*(uint64_t*)(attachedNode+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 0,31);
    // A mesh-only reset is repaired without rebuilding all materials.
    *(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) = 1;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2 && updateCalls == 2,20);
    // No scheduled material rebuilds: stable items stay stable while moving.
    RemoteCache* cache = RemoteCacheFor(&saved);
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 2,21);
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 2,22);
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 2,23);
    *(int*)(weapon+OFF_M_FALLBACKPAINTKIT) = 0;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 756 && updateCalls == 2,28);
    // Recreated scene node triggers fresh material work and mesh restoration.
    uintptr_t replacementNode = Allocate(4096);
    *(uintptr_t*)(weapon+OFF_M_PGAMESCENENODE) = replacementNode;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 3 && *(uint64_t*)(replacementNode+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2,24);
    node = replacementNode;
    // AWP Printstream uses the new mesh; switching from a legacy paint must
    // finish on mesh 1 even when UpdateSkin clears it during rebuilding.
    g_remote[0].cfg.paint = 1206; g_remote[0].cfg.meshMask = 1;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 1206 &&
          *(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 1,25);
    int beforeGap = updateCalls;
    g_remoteCount = 0; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 1206 && updateCalls == beforeGap,26);
    g_remoteCount = 1;
    *(uint8_t*)(node+259) = 1; // dormant keeps the baseline but performs no writes
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == beforeGap && cache->valid,27);
    *(uint8_t*)(node+259) = 0;
    int beforeExpiry = attrCalls;
    RemoteRestore(client,cache); // explicit live removal, not expired permission
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 51 && attrCalls == beforeExpiry+3,13);
    // Default knife -> butterfly uses the world weapon model, then restores.
    uintptr_t originalModel = Allocate(4096);
    copy_str((char*)originalModel,"weapons/models/knife/knife_default_ct.vmdl",320);
    *(uintptr_t*)(node+OFF_M_MODELSTATE+168) = originalModel;
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 42;
    g_remote[0] = saved; g_remote[0].source = 42; g_remote[0].target = 515;
    copy_str(g_remote[0].cfg.model,"weapons/models/knife/knife_butterfly/weapon_knife_butterfly.vmdl",320);
    g_remoteDeadline = remote_now_ms()+3000; g_remoteReadTick = GetTickCount64();
    ApplyRemoteSkins(client);
    Check(*(uint16_t*)(item+OFF_M_ITEMDEFINDEX) == 515 && modelCalls == 1,17);
    Check(vmCalls == 1 && vmWeapon == weapon && *(uint8_t*)(weapon+5816) == 1,29);
    RemoteRestore(client,RemoteCacheFor(&g_remote[0]));
    Check(*(uint16_t*)(item+OFF_M_ITEMDEFINDEX) == 42 && modelCalls == 2,18);
    // Old glove records and direct glove functions must not write anything.
    g_remote[0] = saved; g_remote[0].kind = 1; g_remote[0].handle = 0;
    g_remote[0].target = 5030; g_remote[0].cfg.paint = 10018;
    g_remoteDeadline = remote_now_ms()+3000; g_remoteReadTick = GetTickCount64();
    ApplyRemoteSkins(client);
    ApplyGloves(client,pawn);
    ApplyGloveSkin(pawn,&saved.cfg,5030);
    Check(*(uint16_t*)(pawn+R_GLOVES+OFF_M_ITEMDEFINDEX) == 0,14);
    Check(*(uint8_t*)(pawn+R_REAPPLY_GLOVES) == 0 && modelCalls == 2,15);
    // Owned weapons retain separate caches across a switch. Returning to an
    // unchanged AWP does not restore its default skin and rebuild it again.
    memset(g_remoteCache,0,sizeof(g_remoteCache));
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 9;
    g_remote[0] = saved; g_remoteCount = 1;
    g_remoteDeadline = remote_now_ms()+3000; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    uintptr_t pistol = Allocate(12000), pistolNode = Allocate(4096);
    *(uintptr_t*)(chunk+0x70*201) = pistol;
    *(uint32_t*)(pistol+R_OWNER) = 0x8064;
    *(uintptr_t*)(pistol+OFF_M_PGAMESCENENODE) = pistolNode;
    *(uint16_t*)(RemoteItem(pistol,0)+OFF_M_ITEMDEFINDEX) = 4;
    *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) = 0x80c9;
    g_remote[0].handle = 0x80c9; g_remote[0].source = 4; g_remote[0].target = 4;
    g_remote[0].cfg.paint = 1120;
    RemoteCacheFor(&saved)->lastSeen = 0;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 756 && RemoteCacheFor(&saved)->valid,32);
    int beforeReturn = updateCalls;
    *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) = 0x80c8;
    g_remote[0] = saved; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == beforeReturn && *(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 756,33);
    // Missing seed must trigger a bounded repair even with correct fallback.
    uintptr_t attrs = *(uintptr_t*)(item+536);
    *(uint16_t*)(attrs+72+48) = 99;
    cache = RemoteCacheFor(&saved); cache->lastApply = GetTickCount64()-1000;
    int beforeRepair = updateCalls;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == beforeRepair+1 && RemoteAttr(item,7,-1) == 7,34);
    // A persistent reset is detected but cannot force a heavy call every pass.
    *(float*)(attrs+72+52) = 0;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == beforeRepair+1,35);
    cache->lastApply = GetTickCount64()-1000;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(RemoteAttr(item,7,-1) == 7 && updateCalls == beforeRepair+2,36);

    // Remote -> ground -> local pickup: own AWP paint 344 must not replace 756.
    uintptr_t localWs = Allocate(4096);
    *(uintptr_t*)(chunk+0x70*101) = local;
    *(uint32_t*)(localController+R_PLAYERPAWN) = 0x8065;
    *(int*)(local+R_HEALTH) = 100;
    *(uintptr_t*)(local+OFF_M_PWEAPONSERVICES) = localWs;
    *(uint32_t*)(weapon+R_OWNER) = 0xffffffffu;
    g_remoteCount = 0; cache->lastSeen = 0;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(FindWeaponBinding(client,saved.handle,weapon) != 0,37);
    *(uint32_t*)(weapon+R_OWNER) = 0x8065;
    *(uint32_t*)(localWs+OFF_M_HACTIVEWEAPON) = saved.handle;
    g_skin_count = 1; g_skins[0].def = 9; g_skins[0].cfg = saved.cfg; g_skins[0].cfg.paint = 344;
    ApplyLocalSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 756 && RemoteAttr(item,7,-1) == 7,38);
    Check(FindWeaponBinding(client,saved.handle,weapon)->donor == saved.player,39);
    beforeRepair = updateCalls;
    ApplyLocalSkins(client);
    Check(updateCalls == beforeRepair,40);

    // A distinct local gun gets the local paint, then keeps it for a remote holder.
    uintptr_t donated = Allocate(12000), donatedNode = Allocate(4096);
    *(uintptr_t*)(chunk+0x70*202) = donated;
    *(uintptr_t*)(donated+OFF_M_PGAMESCENENODE) = donatedNode;
    *(uint32_t*)(donated+R_OWNER) = 0x8065;
    *(uint16_t*)(RemoteItem(donated,0)+OFF_M_ITEMDEFINDEX) = 9;
    *(uint32_t*)(localWs+OFF_M_HACTIVEWEAPON) = 0x80ca;
    ApplyLocalSkins(client);
    Check(*(int*)(donated+OFF_M_FALLBACKPAINTKIT) == 344,41);
    *(uint32_t*)(donated+R_OWNER) = 0x8064;
    *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) = 0x80ca;
    g_remote[0] = saved; g_remote[0].handle = 0x80ca; g_remoteCount = 1;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(donated+OFF_M_FALLBACKPAINTKIT) == 344,42);
    // New full handle, same memory and slot: cannot inherit an old donor.
    Check(!FindWeaponBinding(client,0x100ca,donated),43);

    // Local butterfly seed 400 repairs lost attributes and resets on respawn.
    *(uint32_t*)(localWs+OFF_M_HACTIVEWEAPON) = 0x100ca;
    *(uint32_t*)(donated+R_OWNER) = 0x8065;
    uintptr_t donatedItem = RemoteItem(donated,0);
    *(uint16_t*)(donatedItem+OFF_M_ITEMDEFINDEX) = 42;
    g_skins[0].def = 515; g_skins[0].cfg = saved.cfg;
    g_skins[0].cfg.seed = 400; g_skins[0].cfg.paint = 568;
    copy_str(g_skins[0].cfg.model,"weapons/models/knife/knife_butterfly/weapon_knife_butterfly.vmdl",320);
    ApplyLocalSkins(client);
    Check(RemoteAttr(donatedItem,7,-1) == 400 && *(uint16_t*)(donatedItem+OFF_M_ITEMDEFINDEX) == 515,44);
    *(int*)(donatedItem+528) = 0; // all material attributes disappear
    g_localSkin->lastApply = GetTickCount64()-1000;
    ApplyLocalSkins(client);
    Check(RemoteAttr(donatedItem,7,-1) == 400 && RemoteAttr(donatedItem,6,-1) == 568,45);
    *(int*)(donated+OFF_M_FALLBACKSEED) = 0;
    beforeRepair = updateCalls; ApplyLocalSkins(client);
    Check(*(int*)(donated+OFF_M_FALLBACKSEED) == 400 && updateCalls == beforeRepair,46);
    // Pawn serial changed at the same address: forces a fresh presentation.
    *(uint32_t*)(localController+R_PLAYERPAWN) = 0x10065;
    *(uint32_t*)(donated+R_OWNER) = 0x10065;
    ApplyLocalSkins(client);
    Check(updateCalls == beforeRepair+1 && RemoteAttr(donatedItem,7,-1) == 400,47);
    Check(*(int*)(donatedNode+1000) == 0,54);
    int beforeFinalizeModels = modelCalls;
    // One spawn-settle rebuild, then stable again (no recurring timer).
    g_localSkin->settleAt = GetTickCount64()-1; g_localSkin->lastApply = GetTickCount64()-1000;
    ApplyLocalSkins(client);
    Check(updateCalls == beforeRepair+2 && !g_localSkin->settleAt,48);
    Check(modelCalls == beforeFinalizeModels && *(int*)(donatedNode+1000) == 1,55);
    ApplyLocalSkins(client); Check(updateCalls == beforeRepair+2,49);
    // Current ownership is mandatory even when an active handle is stale.
    *(uint32_t*)(donated+R_OWNER) = 0x8064;
    beforeRepair = updateCalls; ApplyLocalSkins(client);
    Check(updateCalls == beforeRepair,51);
    *(uint32_t*)(donated+R_OWNER) = 0x10065;
    // The original donor may update its own gun after getting it back.
    g_skins[0].cfg.seed = 401;
    ApplyLocalSkins(client);
    Check(RemoteAttr(donatedItem,7,-1) == 401 &&
        FindWeaponBinding(client,0x100ca,donated)->cfg.seed == 401,52);
    // A new identity at a reused address invalidates the old binding.
    *(uintptr_t*)(donated+16) = Allocate(128);
    Check(!FindWeaponBinding(client,0x100ca,donated),53);
    ApplyLocalSkins(client);
    // Map/session transition clears all physical-weapon bindings.
    *(uintptr_t*)(client+OFF_DW_GAMERULES) = 234567;
    g_control.rules = 234567;
    Check(!FindWeaponBinding(client,0x100ca,donated),50);
    // Remote model finalization uses the same material-only second stage.
    memset(g_remoteCache,0,sizeof(g_remoteCache));
    g_remoteRules = 234567;
    *(uint32_t*)(weapon+R_OWNER) = 0x8064;
    *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) = saved.handle;
    *(uint16_t*)(item+OFF_M_ITEMDEFINDEX) = 42;
    g_remote[0] = saved; g_remote[0].source = 42; g_remote[0].target = 515;
    g_remote[0].cfg = g_skins[0].cfg; g_remoteCount = 1;
    g_remoteDeadline = remote_now_ms()+3000; g_remoteReadTick = GetTickCount64();
    ApplyRemoteSkins(client);
    Check(*(int*)(node+1000) == 0 && !SkinAttributesWrong(weapon,&g_remote[0].cfg),56);
    cache = RemoteCacheFor(&g_remote[0]);
    cache->settleAt = GetTickCount64()-1; cache->lastApply = GetTickCount64()-1000;
    beforeFinalizeModels = modelCalls;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(modelCalls == beforeFinalizeModels && *(int*)(node+1000) == 1 && !cache->settleAt,57);
    // Selecting a new paint on the SAME knife must not reset the world model.
    g_remote[0].cfg.paint = 570;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(modelCalls == beforeFinalizeModels && cache->settleAt != 0,58);
    // Unconfigured pistol: no bridge record, but retain the holstered knife.
    *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) = 0x80c9;
    g_remoteCount = 0; cache->lastSeen = GetTickCount64()-10000;
    beforeRepair = updateCalls;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(cache->valid && updateCalls == beforeRepair,59);
    *(uint32_t*)(ws+OFF_M_HACTIVEWEAPON) = saved.handle;
    g_remoteCount = 1; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == beforeRepair,60);
    // Local switching also reuses the physical weapon's settled cache.
    *(uint32_t*)(localWs+OFF_M_HACTIVEWEAPON) = 0x100ca;
    g_skins[0].def = 515; ApplyLocalSkins(client);
    LocalSkinState* knifeCache = g_localSkin;
    knifeCache->settleAt = 0;
    *(uint32_t*)(pistol+R_OWNER) = 0x10065;
    *(uint32_t*)(localWs+OFF_M_HACTIVEWEAPON) = 0x80c9;
    g_skin_count = 2; g_skins[1].def = 4; g_skins[1].cfg = saved.cfg;
    ApplyLocalSkins(client);
    beforeRepair = updateCalls;
    *(uint32_t*)(localWs+OFF_M_HACTIVEWEAPON) = 0x100ca;
    ApplyLocalSkins(client);
    Check(g_localSkin == knifeCache && updateCalls == beforeRepair,61);
    // A transient invalid active handle is not a new pawn/selection.
    *(uint32_t*)(localWs+OFF_M_HACTIVEWEAPON) = 0xffffffffu;
    ApplyLocalSkins(client);
    *(uint32_t*)(localWs+OFF_M_HACTIVEWEAPON) = 0x100ca;
    ApplyLocalSkins(client); Check(updateCalls == beforeRepair,62);
    // Incomplete local files cannot partially replace the current loadout.
    int previousCount = g_skin_count;
    const char incomplete[] = "9 1206 400";
    Check(!CommitLocalConfig(incomplete,incomplete+sizeof(incomplete)-1) && g_skin_count == previousCount,63);
    const char complete[] = "515 568 400 0.01 1 weapons/models/knife/knife_butterfly/weapon_knife_butterfly.vmdl\n";
    Check(CommitLocalConfig(complete,complete+sizeof(complete)-1) && g_skin_count == 1 && g_skins[0].cfg.seed == 400,64);
    // Malformed/overflow input fails closed, clearing the render batch.
    const char badFile[] = "CS2PY_REMOTE_V1 18446744073709551616 0 0 0";
    Check(!RemoteParse(badFile,badFile+sizeof(badFile)-1) && g_remoteCount == 0,16);
    // Disabled entry points must not repair fields, models or cached restores.
    beforeRepair = attrCalls + updateCalls + modelCalls;
    *(int*)(donated+OFF_M_FALLBACKPAINTKIT) = -123;
    *(int*)(weapon+OFF_M_FALLBACKPAINTKIT) = -123;
    g_localEnabled = g_shareEnabled = 0;
    ApplyLocalSkins(client); ApplyRemoteSkins(client);
    RemoteRestore(client,cache);
    Check(*(int*)(donated+OFF_M_FALLBACKPAINTKIT) == -123 &&
        *(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == -123 &&
        beforeRepair == attrCalls+updateCalls+modelCalls,65);
    // Local toggle off still permits donor pickups, but not own saved loadout.
    g_shareEnabled = 1;
    ApplyLocalSkins(client);
    Check(*(int*)(donated+OFF_M_FALLBACKPAINTKIT) == -123,66);
    g_localEnabled = 1;
    *(int*)(network+OFF_ENGINE_SIGNON) = 0;
    ApplyLocalSkins(client); ApplyRemoteSkins(client);
    Check(*(int*)(donated+OFF_M_FALLBACKPAINTKIT) == -123 &&
        beforeRepair == attrCalls+updateCalls+modelCalls,67);
    *(int*)(network+OFF_ENGINE_SIGNON) = 6;
    g_control.deadline = 0;
    ApplyLocalSkins(client); ApplyRemoteSkins(client);
    Check(*(int*)(donated+OFF_M_FALLBACKPAINTKIT) == -123,68);
    g_control.deadline = remote_now_ms()+3000;
    cache->valid = 1;
    g_remoteDeadline = 0; g_remoteReadTick = GetTickCount64();
    ApplyRemoteSkins(client);
    Check(!cache->valid && *(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == -123 &&
        beforeRepair == attrCalls+updateCalls+modelCalls,74);
    // An unmapped client root returns zero rather than faulting on teardown.
    uintptr_t freed = Allocate(4096);
    VirtualFree((void*)freed,0,MEM_RELEASE);
    Check(ReadRoot(freed) == 0 && !RendererSessionCurrent(freed),69);
    const char control[] = "CS2PY_CONTROL_V1 123 1100 1 1 123456 234567";
    Check(ControlParse(control,control+sizeof(control)-1,123,1000) && g_localEnabled && g_shareEnabled,70);
    Check(!ControlParse(control,control+sizeof(control)-1,124,1000) && !g_localEnabled && !g_shareEnabled,71);
    Check(!ControlParse(control,control+sizeof(control)-1,123,1100) && !g_localEnabled && !g_shareEnabled,72);
    const char malformedControl[] = "CS2PY_CONTROL_V1 123 1100 2 1 123456 234567";
    Check(!ControlParse(malformedControl,malformedControl+sizeof(malformedControl)-1,123,1000),73);
    ExitProcess(0);
}
