// Copyright Epic Games, Inc. All Rights Reserved.

#include "OpenWorldProp.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "OpenWorldPhysicalMaterial.h"
#include "OpenWorld.h"

AOpenWorldProp::AOpenWorldProp()
{
	PrimaryActorTick.bCanEverTick = false;

	Mesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Mesh"));
	SetRootComponent(Mesh);
	Mesh->SetCollisionProfileName(TEXT("BlockAll"));
	Mesh->SetMobility(EComponentMobility::Movable);
}

void AOpenWorldProp::Configure(UStaticMesh* InMesh, UMaterialInterface* InMaterial, UOpenWorldPhysicalMaterial* InSubstance,
	FVector InScale, bool bInSimulatePhysics, float InDurability)
{
	Mesh->SetStaticMesh(InMesh);
	Mesh->SetWorldScale3D(InScale);
	if (InMaterial && InMesh)
	{
		for (int32 Index = 0; Index < Mesh->GetNumMaterials(); ++Index)
		{
			Mesh->SetMaterial(Index, InMaterial);
		}
	}

	// The substance decides how contacts with the prop behave (hardness) and how heavy it is (density)
	Mesh->SetPhysMaterialOverride(InSubstance);
	Mesh->SetCollisionProfileName(bInSimulatePhysics ? TEXT("PhysicsActor") : TEXT("BlockAll"));
	Mesh->SetSimulatePhysics(bInSimulatePhysics);

	Durability = InDurability;
}

void AOpenWorldProp::ApplyDamage(float Damage, AActor* DamageCauser, const FVector& DamageLocation, const FVector& DamageImpulse)
{
	if (Mesh->IsSimulatingPhysics())
	{
		Mesh->AddImpulseAtLocation(DamageImpulse, DamageLocation);
	}

	if (Durability > 0.f)
	{
		Durability -= Damage;
		if (Durability <= 0.f)
		{
			HandleDeath();
		}
	}
}

void AOpenWorldProp::HandleDeath()
{
	UE_LOG(LogOpenWorld, Display, TEXT("Prop '%s' broke."), *GetNameSafe(this));
	Destroy();
}
