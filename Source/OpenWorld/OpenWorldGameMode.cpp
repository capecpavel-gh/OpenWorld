// Copyright Epic Games, Inc. All Rights Reserved.

#include "OpenWorldGameMode.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/PlayerStart.h"
#include "Kismet/GameplayStatics.h"
#include "Materials/MaterialInterface.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "OpenWorldPhysicalMaterial.h"
#include "OpenWorldProp.h"
#include "OpenWorld.h"

AOpenWorldGameMode::AOpenWorldGameMode()
{
	// stub
}

void AOpenWorldGameMode::BeginPlay()
{
	Super::BeginPlay();

	// The scripted self-test places its own targets
	if (!bSpawnTestProps || FParse::Param(FCommandLine::Get(), TEXT("OWSelfTest")))
	{
		return;
	}

	const AActor* Start = UGameplayStatics::GetActorOfClass(this, APlayerStart::StaticClass());
	if (!Start)
	{
		return;
	}

	// A row across the player's view: steel and wood, fixed and loose
	const TArray<TPair<FName, FName>> Row = {
		{ TEXT("Wood"), TEXT("Post") },
		{ TEXT("Steel"), TEXT("Block") },
		{ TEXT("Wood"), TEXT("Crate") },
		{ TEXT("Steel"), TEXT("Crate") },
		{ TEXT("Wood"), TEXT("Shield") },
	};

	const FVector Forward = Start->GetActorForwardVector().GetSafeNormal2D();
	const FVector Right = FVector::CrossProduct(FVector::UpVector, Forward);
	const float Yaw = Forward.Rotation().Yaw;
	for (int32 Index = 0; Index < Row.Num(); ++Index)
	{
		const float Side = (Index - (Row.Num() - 1) * 0.5f) * TestPropSpacing;
		SpawnTestProp(Row[Index].Key, Row[Index].Value, Start->GetActorLocation() + Forward * TestPropDistance + Right * Side, Yaw);
	}
}

AOpenWorldProp* AOpenWorldGameMode::SpawnTestProp(FName Substance, FName Shape, FVector GroundLocation, float Yaw)
{
	const bool bSteel = Substance == TEXT("Steel");
	UOpenWorldPhysicalMaterial* PhysicalMaterial = LoadObject<UOpenWorldPhysicalMaterial>(nullptr,
		bSteel ? TEXT("/Game/Materials/Substances/PM_Steel.PM_Steel") : TEXT("/Game/Materials/Substances/PM_Wood.PM_Wood"));
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr,
		bSteel ? TEXT("/Game/Materials/Substances/MI_Steel.MI_Steel") : TEXT("/Game/Materials/Substances/MI_Wood.MI_Wood"));

	// Shape: mesh, scale, half height [cm], can be knocked around, durability
	const TCHAR* MeshPath = TEXT("/Engine/BasicShapes/Cube.Cube");
	FVector Scale(0.6f, 0.6f, 1.2f);
	float HalfHeight = 60.f;
	bool bLoose = false;
	float Durability = 0.f;
	FRotator Rotation(0.f, Yaw, 0.f);
	if (Shape == TEXT("Post"))
	{
		MeshPath = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
		Scale = FVector(0.3f, 0.3f, 1.8f);
		HalfHeight = 90.f;
	}
	else if (Shape == TEXT("Crate"))
	{
		// tall enough to stand in the path of a cut
		Scale = FVector(0.6f, 0.6f, 1.1f);
		HalfHeight = 55.f;
		bLoose = true;
		Durability = bSteel ? 0.f : 12.f;
	}
	else if (Shape == TEXT("Shield"))
	{
		// The player's own shield, standing on its rim and facing the player
		MeshPath = TEXT("/Game/Weapons/Shield/SM_Shield.SM_Shield");
		Scale = FVector::OneVector;
		HalfHeight = 33.f;
		bLoose = true;
		Material = nullptr;     // keeps its own wood and steel materials
		Rotation.Yaw += 180.f;
	}

	UStaticMesh* PropMesh = LoadObject<UStaticMesh>(nullptr, MeshPath);
	if (!PropMesh)
	{
		UE_LOG(LogOpenWorld, Warning, TEXT("Test prop mesh '%s' is missing."), MeshPath);
		return nullptr;
	}

	// Stand the prop on whatever is below the requested spot
	FVector Ground = GroundLocation;
	FHitResult Floor;
	if (GetWorld()->LineTraceSingleByChannel(Floor, GroundLocation + FVector(0, 0, 200.f), GroundLocation - FVector(0, 0, 1000.f), ECC_WorldStatic))
	{
		Ground = Floor.ImpactPoint;
	}

	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AOpenWorldProp* Prop = GetWorld()->SpawnActor<AOpenWorldProp>(Ground + FVector(0, 0, HalfHeight + 1.f), Rotation, Params);
	if (Prop)
	{
		Prop->Configure(PropMesh, Material, PhysicalMaterial, Scale, bLoose, Durability);
		if (Shape == TEXT("Crate"))
		{
			// A crate is hollow: far lighter than a solid block of its substance
			Prop->GetMesh()->SetMassOverrideInKg(NAME_None, bSteel ? 120.f : 35.f, true);
		}
	}
	return Prop;
}
