// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "OpenWorldPhysicalMaterial.generated.h"

/**
 *  Physical material of the game: Unreal's friction, restitution and density, plus how the
 *  substance behaves when something strikes it. Decides what a contact does (see the project rule
 *  "nothing passes through anything": motion stops at the surface, then the materials decide).
 */
UCLASS()
class UOpenWorldPhysicalMaterial : public UPhysicalMaterial
{
	GENERATED_BODY()

public:

	/** Name shown in contact reports, e.g. "Steel" */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Substance")
	FText DisplayName;

	/** Resistance to being cut or dented, on a Mohs-like scale (wood about 2.5, hardened steel about 7.5) */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Substance", meta=(ClampMin="0.1", ClampMax="10"))
	float Hardness = 5.f;

	/** How much punishment an object made of this takes before it breaks, relative to 1 */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Substance", meta=(ClampMin="0.01"))
	float Toughness = 1.f;
};
