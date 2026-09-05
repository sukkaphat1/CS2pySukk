// Isolated fake-memory fixtures. Never opens or writes to a game process.
// Build CRT-free with /ENTRY:RemoteTestMain and kernel32.lib.
#include "skinchanger.cpp"

static int attrCalls = 0, updateCalls = 0, modelCalls = 0, vmCalls = 0;
static uintptr_t vmWeapon = 0;
static void __fastcall FakeWeaponVm(void* entity) { vmCalls++; vmWeapon = (uintptr_t)entity; }
static void __fastcall FakeSubclass(void*) {}
static void __fastcall FakeAttr(void*,const char*,float) { attrCalls++; }
static void __fastcall FakeUpdate(void* entity,bool) {
    updateCalls++;
    // Reproduce a material refresh resetting the visible mesh.
    uintptr_t node = *(uintptr_t*)((uintptr_t)entity+OFF_M_PGAMESCENENODE);
    if (node) *(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) = 0;
}
static void __fastcall FakeModel(void*,const char*) { modelCalls++; }
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
    Check(*(uint64_t*)(node+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2 && updateCalls == 1,20);
    // No scheduled material rebuilds: stable items stay stable while moving.
    RemoteCache* cache = RemoteCacheFor(&saved);
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 1,21);
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 1,22);
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 1,23);
    *(int*)(weapon+OFF_M_FALLBACKPAINTKIT) = 0;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(*(int*)(weapon+OFF_M_FALLBACKPAINTKIT) == 756 && updateCalls == 1,28);
    // Recreated scene node triggers fresh material work and mesh restoration.
    uintptr_t replacementNode = Allocate(4096);
    *(uintptr_t*)(weapon+OFF_M_PGAMESCENENODE) = replacementNode;
    g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
    Check(updateCalls == 2 && *(uint64_t*)(replacementNode+OFF_M_MODELSTATE+OFF_M_MESHGROUPMASK) == 2,24);
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
    g_remoteDeadline = 0; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
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
    g_remoteDeadline = 0; g_remoteReadTick = GetTickCount64(); ApplyRemoteSkins(client);
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
    // Malformed/overflow input fails closed, clearing the render batch.
    const char badFile[] = "CS2PY_REMOTE_V1 18446744073709551616 0 0 0";
    Check(!RemoteParse(badFile,badFile+sizeof(badFile)-1) && g_remoteCount == 0,16);
    ExitProcess(0);
}
