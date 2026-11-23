// Copyright Epic Games, Inc. All Rights Reserved.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "CombatDamageable.h"
#include "OpenWorldProp.generated.h"

class UStaticMesh;
class UStaticMeshComponent;
class UMaterialInterface;
class UOpenWorldPhysicalMaterial;

/**
 *  A solid object made of one substance: a post, a block, a crate. It blocks weapons at its surface,
 *  is pushed by hits when it simulates physics, and breaks when its durability runs out.
 */
UCLASS()
class AOpenWorldProp : public AActor, public ICombatDamageable
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components", meta = (AllowPrivateAccess = "true"))
	UStaticMeshComponent* Mesh;

public:

	AOpenWorldProp();

	/** Sets what the prop looks like, what it is made of and whether hits can move it */
	UFUNCTION(BlueprintCallable, Category="Prop")
	void Configure(UStaticMesh* InMesh, UMaterialInterface* InMaterial, UOpenWorldPhysicalMaterial* InSubstance,
		FVector InScale, bool bInSimulatePhysics, float InDurability);

	UFUNCTION(BlueprintPure, Category="Prop")
	float GetDurability() const { return Durability; }

	FORCEINLINE UStaticMeshComponent* GetMesh() const { return Mesh; }

	// ICombatDamageable
	virtual void ApplyDamage(float Damage, AActor* DamageCauser, const FVector& DamageLocation, const FVector& DamageImpulse) override;
	virtual void HandleDeath() override;
	virtual void ApplyHealing(float Healing, AActor* Healer) override {}
	virtual void NotifyDanger(const FVector& DangerLocation, AActor* DangerSource) override {}

protected:

	/** Damage the prop takes before it breaks; 0 or less = unbreakable */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Prop")
	float Durability = 0.f;
};
